#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr  6 10:49:38 2020

@author: worklab
"""

import torch
import numpy as np
import matplotlib.pyplot as plt


class torch_KF(object):
    def __init__(self,device):
        # initialize tensors
        state_size = 7
        self.state_size = state_size
        meas_size = 4
        mod_err = 1
        meas_err = 1
        state_err =1
        self.t = 1/30.0
        
        self.P0 = torch.zeros(state_size,state_size) # state covariance

        self.F = torch.zeros(state_size,state_size) # dynamical model
        self.H = torch.zeros(meas_size,state_size)  # measurement model
        self.Q = torch.zeros(state_size,state_size) # model covariance
        self.R = torch.zeros(meas_size,meas_size)   # measurement covariance
        
        # obj_ids[a] stores index in X along dim 0 where object a is stored
        self.obj_idxs = {}
        
        #self.obj_history = {}
        """
        obj_history template -indexed by integer object id
        {class: (int),
         first_frame: (int),
         detected: (binary list),
         states: (list of states)
        }
        """
        
        # set intial value for state covariance
        self.P0 = torch.eye(state_size).unsqueeze(0) * state_err
        
        # these values won't change 
        self.F = torch.eye(state_size).float()
        self.F[[0,1,2],[4,5,6]] = self.t
        self.H[:4,:4] = torch.eye(4)
        self.Q = torch.eye(state_size).unsqueeze(0) * mod_err
        self.R = torch.eye(meas_size).unsqueeze(0) * meas_err
        
    def add(self,detections,obj_ids):
        """
        Initializes KF matrices if first object, otherwise adds new object to matrices
        detection - n x 4 np array with x,y,s,r
        obj_ids - list of length n with unique obj_id (int) for each detection
        """
        
        newX = torch.zeros((len(detections),self.state_size))
        newX[:,:4] = torch.from_numpy(detections)
        newP = self.P0.repeat(len(obj_ids),1,1)

        # store state and initialize P with defaults
        try:
            new_idx = len(self.X)
            self.X = torch.cat((self.X,newX), dim = 0)
            self.P = torch.cat((self.P,newP), dim = 0)
        except:
            new_idx = 0
            self.X = newX
            self.P = newP
            
        # add obj_ids to dictionary
        for id in obj_ids:
            self.obj_idxs[id] = new_idx
            new_idx = new_idx + 1
        
    
    def remove(self,obj_ids):
        """
        
        """
        keepers = list(range(len(self.X)))
        for id in obj_ids:
            keepers.remove(self.obj_idxs[id])
            self.obj_idxs[id] = None    
        keepers.sort()
        
        self.X = self.X[keepers,:]
        self.P = self.P[keepers,:]
    
    
    def predict(self):
        """
        Uses KF to propagate object locations
        """
        
        
        # update X --> X = XF--> [n,7] x [7,7] = [n,7]
        self.X = torch.mm(self.X,self.F) 
        
        # update P --> P = FPF^(-1) + Q
        step1 = torch.mul(self.F,self.P)
        step2 = self.F.inverse()
        step3 = torch.mul(step1,step2)
        step4 = self.Q.repeat(len(self.P),1,1)
        self.P = step3 + step4
        
    def update(self,detections,obj_ids):
        """
        Updates state for objects corresponding to each obj_id in obj_ids
        Equations taken from: wikipedia.org/wiki/Kalman_filter#Predict
        detections - nx4
        obj_ids - list of length n
        """
        
        # get relevant portions of X and P
        relevant = [self.obj_idxs[id] for id in obj_ids]
        X_up = self.X[relevant,:]
        P_up = self.P[relevant,:,:]
        
        # state innovation --> y = z - XHt --> mx4 = mx4 - [mx7] x [4x7]t  
        z = torch.from_numpy(detections)
        y = z - torch.mm(X_up, self.H.transpose(0,1))
        
        # covariance innovaton --> HPHt + R --> [mx4x4] = [mx4x7] bx [mx7x7] bx [mx4x7]t + [mx4x4]
        # where bx is batch matrix multiplication broadcast along dim 0
        # in this case, S = [m,4,4]
        H_rep = self.H.unsqueeze(0).repeat(len(P_up),1,1)
        step1 = torch.bmm(H_rep,P_up) # this needs to be batched along dim 0
        step2 = torch.bmm(step1,H_rep.transpose(1,2))
        S = step2 + self.R.repeat(len(P_up),1,1)
        
        # kalman gain --> K = P Ht S^(-1) --> [m,7,4] = [m,7,7] bx [m,7,4]t bx [m,4,4]^-1
        step1 = torch.bmm(P_up,H_rep.transpose(1,2))
        K = torch.bmm(step1,S.inverse())
        
        # A posteriori state estimate --> X_updated = X + Ky --> [mx7] = [mx7] + [mx7x4] bx [mx4x1]
        # must first unsqueeze y to third dimension, then unsqueeze at end
        y = y.unsqueeze(-1).float() # [mx4] --> [mx4x1]
        step1 = torch.bmm(K,y).squeeze(-1) # mx7
        X_up = X_up + step1
        
        # P_updated --> (I-KH)P --> [m,7,7] = ([m,7,7 - [m,7,4] bx [m,4,7]) bx [m,7,7]    
        I = torch.eye(7).unsqueeze(0).repeat(len(P_up),1,1)
        step1 = I - torch.bmm(K,H_rep)
        P_up = torch.bmm(step1,P_up)
        
        # store updated values
        self.X[relevant,:] = X_up
        self.P[relevant,:,:] = P_up
        
    def objs(self):
        """
        Returns current state of each object as dict
        """
        
        out_dict = {}
        for id in self.obj_idxs:
            idx = self.obj_idxs[id]
            if idx is not None:
                out_dict[id] = self.X[idx,:]
        return out_dict        

if __name__ == "__main__":
    """
    A test script in which bounding boxes are randomly generated and jittered to create motion
    """
    ids = [0,1,2,3,4,5,6,7,8,9]
    detections = np.random.rand(10,4)*50

    colors = np.random.rand(1000,4)
    colors2 = colors.copy()
    colors[:,3]  = 0.2
    colors2[:,3] = 1
    filter = torch_KF(None)
    filter.add(detections,ids)
    for i in range(0,500):
        
        filter.predict()
        
        detections = detections + np.random.normal(0,1,[10,4]) + 1
        detections[:,2:] = detections[:,2:]/50
        remove = np.random.randint(0,9)
        
        ids_r = ids.copy()
        del ids_r[remove]
        det_r = detections[ids_r,:]
        filter.update(det_r,ids_r)
        tracked_objects = filter.objs()
        
        # plot the points to visually confirm that it seems to be working 
        x_coords = []
        y_coords = []
        for key in tracked_objects:
            x_coords.append(tracked_objects[key][0])
            y_coords.append(tracked_objects[key][1])
        for i in range(len(x_coords)):
            if i < len(x_coords) -1:
                plt.scatter(det_r[i,0],det_r[i,1], color = colors2[i])
            plt.scatter(x_coords[i],y_coords[i],s = 300,color = colors[i])
            plt.annotate(i,(x_coords[i],y_coords[i]))
        plt.draw()
        plt.pause(0.001)
        plt.clf()
        
        
        
       
