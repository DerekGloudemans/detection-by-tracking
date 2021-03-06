"""
This file provides a dataset class for working with the UA-detrac tracking dataset.
Provides:
    - plotting of 2D bounding boxes
    - training/testing loader mode (random images from across all tracks) using __getitem__()
    - track mode - returns a single image, in order, using __next__()
"""

import os
import numpy as np
import random 
random.seed = 0

import cv2
from PIL import Image
import torch
from torch.utils import data
from torchvision import transforms

import xml.etree.ElementTree as ET

try:
    from detrac_files.detrac_plot_utils_copy import pil_to_cv, plot_bboxes_2d
except:
    from detrac_plot_utils_copy import pil_to_cv, plot_bboxes_2d


class Track_Dataset(data.Dataset):
    """
    Creates an object for referencing the UA-Detrac 2D object tracking dataset
    Note that __getitem__ based indexing keeps data separated into testing and training
    sets whereas __next__ based retreival does not, so the latter should only 
    be used for plotting sequences
    """
    
    def __init__(self, image_dir, label_dir, mode = "training"):
        """ initializes object. By default, the first track (cur_track = 0) is loaded 
        such that next(object) will pull next frame from the first track
        image dir - (string) - a directory containing a subdirectory for each track sequence
        label dir - (string) - a directory containing a label file per sequence
        mode - (string) - training or testing
        """

        # stores files for each set of images and each label
        dir_list = next(os.walk(image_dir))[1]
        track_list = [os.path.join(image_dir,item) for item in dir_list]
        label_list = [os.path.join(label_dir,item) for item in os.listdir(label_dir)]
        track_list.sort()
        label_list.sort()
        
        self.im_tf = transforms.ToTensor()
        
        # for storing data
        self.track_offsets = [0]
        self.track_metadata = []
        self.all_data = []
        
        # parse and store all labels and image names in a list such that
        # all_data[i] returns dict with image name, label and other stats
        # track_offsets[i] retuns index of first frame of track[i[]]
        for i in  range(0,2): #range(0,len(track_list)):

            images = [os.path.join(track_list[i],frame) for frame in os.listdir(track_list[i])]
            images.sort() 
            labels,metadata = self.parse_labels(label_list[i])
            self.track_metadata.append(metadata)
            
            
            for j in range(len(images)):
                try:
                    out_dict = {
                            'image':images[j],
                            'label':labels[j],
                            'track_len': len(images),
                            'track_num': i,
                            'frame_num_of_track':j
                            }
                    self.all_data.append(out_dict)
                except:
                    print("Error: tried to load label {} for track {} but it doesnt exist. Labels is length {}".format(j,i,len(labels)))
            # index of first frame
            if i < len(track_list) - 1:
                self.track_offsets.append(len(images)+self.track_offsets[i])
            
        # for keeping frames and track sequences
        self.cur_track =  None # int
        self.cur_frame = None
        self.num_tracks = len(track_list)
        self.total_num_frames = len(self.all_data)
        
        # in case it is later important which files are which
        self.track_list = track_list
        self.label_list = label_list
        
        # for separating training 80% and testing 20% data
        self.mode = mode
        idxs = [i for i in range(len(self.all_data))]
        random.shuffle(idxs)
        cutoff = int(len(self.all_data)*0.8)
        self.train_idxs = idxs[:cutoff]
        self.test_idxs = idxs[cutoff:]
        
        # load track 0
        self.load_track(0)
        
        
    def load_track(self,idx):
        """moves to track indexed by idx (int)."""
        try:
            if idx >= self.num_tracks or idx < 0:
                raise Exception
                
            self.cur_track = idx
            # so that calling next will load frame 0 of that track
            self.cur_frame = self.track_offsets[idx]-1 
        except:
            print("Invalid track number")
            
    def num_tracks(self):
        """ return number of tracks"""
        return self.num_tracks
    
    def __next__(self):
        """get next frame label, and a bit of other info from current track"""
                
        self.cur_frame = self.cur_frame + 1
        cur = self.all_data[self.cur_frame]
        im = Image.open(cur['image'])
        label = cur['label']
        track_len = cur['track_len']
        frame_num_of_track = cur['frame_num_of_track']
        track_num = cur['track_num']
        metadata = self.track_metadata[track_num]
        
        return im, label, frame_num_of_track, track_len, track_num, metadata


    def __len__(self):
        """ returns total number of frames in all tracks"""
        if self.mode == "training":
            return len(self.train_idxs)
        else:
            return len(self.test_idxs)
       # return self.total_num_frames
    
    def __getitem__(self,index):
        """ returns item indexed from all frames in all tracks from training
        or testing indices depending on mode
        """
        
        if self.mode == "training":
            true_idx = self.train_idxs[index]
        else:
            true_idx = self.test_idxs[index]
            
        cur = self.all_data[true_idx]
        im = Image.open(cur['image'])
        label = cur['label']
        
        # convert image and label to tensors
        im = self.im_tf(im)
        all_bboxes = []
        all_cls = []
        for item in label:
            all_bboxes.append( torch.from_numpy(item['bbox']).float() )
            val = item['class_num']
            all_cls.append(  torch.tensor(val).long() )
        
        all_bboxes = torch.stack(all_bboxes,dim = 0)
        all_cls = torch.stack(all_cls)
        
        label = {
                'boxes': all_bboxes,
                'labels':all_cls
                }
        
        
        return im, label
    
    def parse_labels(self,label_file):
        """
        Returns a set of metadata (1 per track) and a list of labels (1 item per
        frame, where an item is a list of dictionaries (one dictionary per object
        with fields id, class, truncation, orientation, and bbox
        """
        
        class_dict = {
            'Sedan':0,
            'Hatchback':1,
            'Suv':2,
            'Van':3,
            'Police':4,
            'Taxi':5,
            'Bus':6,
            'Truck-Box-Large':7,
            'MiniVan':8,
            'Truck-Box-Med':9,
            'Truck-Util':10,
            'Truck-Pickup':11,
            'Truck-Flatbed':12,
            
            0:'Sedan',
            1:'Hatchback',
            2:'Suv',
            3:'Van',
            4:'Police',
            5:'Taxi',
            6:'Bus',
            7:'Truck-Box-Large',
            8:'MiniVan',
            9:'Truck-Box-Med',
            10:'Truck-Util',
            11:'Truck-Pickup',
            12:'Truck-Flatbed'
            }
        
        
        tree = ET.parse(label_file)
        root = tree.getroot()
        
        # get sequence attributes
        seq_name = root.attrib['name']
        
        # get list of all frame elements
        frames = root.getchildren()
        
        # first child is sequence attributes
        seq_attrs = frames[0].attrib
        
        # second child is ignored regions
        ignored_regions = []
        for region in frames[1]:
            coords = region.attrib
            box = np.array([float(coords['left']),
                            float(coords['top']),
                            float(coords['left']) + float(coords['width']),
                            float(coords['top'])  + float(coords['height'])])
            ignored_regions.append(box)
        frames = frames[2:]
        
        # rest are bboxes
        all_boxes = []
        for frame in frames:
            frame_boxes = []
            boxids = frame.getchildren()[0].getchildren()
            for boxid in boxids:
                data = boxid.getchildren()
                coords = data[0].attrib
                stats = data[1].attrib
                bbox = np.array([float(coords['left']),
                                float(coords['top']),
                                float(coords['left']) + float(coords['width']),
                                float(coords['top'])  + float(coords['height'])])
                det_dict = {
                        'id':int(boxid.attrib['id']),
                        'class':stats['vehicle_type'],
                        'class_num':class_dict[stats['vehicle_type']],
                        'color':stats['color'],
                        'orientation':float(stats['orientation']),
                        'truncation':float(stats['truncation_ratio']),
                        'bbox':bbox
                        }
                
                frame_boxes.append(det_dict)
            all_boxes.append(frame_boxes)
        
        sequence_metadata = {
                'sequence':seq_name,
                'seq_attributes':seq_attrs,
                'ignored_regions':ignored_regions
                }
        return all_boxes, sequence_metadata
    
    def plot(self,track_idx,SHOW_LABELS = True):
        """ plots all frames in track_idx as video
            SHOW_LABELS - if True, labels are plotted on sequence
            track_idx - int    
        """

        self.load_track(track_idx)
        im,label,frame_num,track_len,track_num,metadata = next(self)
        
        while True:
            cv_im = pil_to_cv(im)
            
            if SHOW_LABELS:
                cv_im = plot_bboxes_2d(cv_im,label,metadata['ignored_regions'])
                
            cv2.imshow("Frame",cv_im)
            key = cv2.waitKey(0) & 0xff
            #time.sleep(1/30.0)
            
            if key == ord('q'):
                break
            
            # load next frame
            im,label,frame_num,track_len,track_num,metadata = next(self)
            if frame_num == track_len - 1:
                break
    
        cv2.destroyAllWindows()
        

if __name__ == "__main__":
    #### Test script here
    label_dir = "C:\\Users\\derek\\Desktop\\UA Detrac\\DETRAC-Train-Annotations-XML-v3"
    image_dir = "C:\\Users\\derek\\Desktop\\UA Detrac\\Tracks"
    label_dir = "/home/worklab/Desktop/detrac/DETRAC-Train-Annotations-XML-v3"
    image_dir = "/home/worklab/Desktop/detrac/DETRAC-all-data"
    test = Track_Dataset(image_dir,label_dir)
    test.plot(0)
    temp = test[0]

