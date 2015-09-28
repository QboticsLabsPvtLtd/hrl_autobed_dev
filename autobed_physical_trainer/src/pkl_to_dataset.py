#!/usr/bin/env python
import sys
import os
import numpy as np
import cPickle as pkl
import random

# ROS
import roslib; roslib.load_manifest('autobed_physical_trainer')

# Graphics
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# Machine Learning
from scipy import ndimage
from scipy.ndimage.filters import gaussian_filter
## from skimage import data, color, exposure
from sklearn.decomposition import PCA

# HRL libraries
import hrl_lib.util as ut


MAT_WIDTH = 0.762 #metres
MAT_HEIGHT = 1.854 #metres
MAT_HALF_WIDTH = MAT_WIDTH/2 
NUMOFTAXELS_X = 64#73 #taxels
NUMOFTAXELS_Y = 27#30 
INTER_SENSOR_DISTANCE = 0.0286#metres
LOW_TAXEL_THRESH_X = 0
LOW_TAXEL_THRESH_Y = 0
HIGH_TAXEL_THRESH_X = (NUMOFTAXELS_X - 1) 
HIGH_TAXEL_THRESH_Y = (NUMOFTAXELS_Y - 1) 

 
class DatabaseCreator():
    '''Gets the directory of pkl database and iteratively go through each file,
    cutting up the pressure maps and creating synthetic database'''
    def __init__(self, training_database_pkl_directory, save_pdf=False, verbose=False):

        # Set initial parameters
        self.training_dump_path = training_database_pkl_directory.rstrip('/')
        self.save_pdf           = save_pdf
        self.verbose            = verbose

        home_sup_dat = pkl.load(
                open(os.path.join(self.training_dump_path,'home_sup.p'), "r"))         

        [self.p_world_mat, self.R_world_mat] = pkl.load(
                open(os.path.join(self.training_dump_path,'mat_axes.p'), "r"))         


       #Pop the mat coordinates from the dataset
#        try:
            #self.p_world_mat = home_sup_dat.pop('mat_o') 
        #except:
            #print "[Warning] MAT ORIGIN HAS NOT BEEN CAPTURED."
            #print "[Warning] Either retrain system or get mat older mat_origin"
            #self.p_world_mat = [0.289, 1.861, 0.546]

        self.mat_size = (NUMOFTAXELS_X, NUMOFTAXELS_Y)
        #Remove empty elements from the dataset, that may be due to Motion
        #Capture issues.
        if self.verbose: print "Checking database for empty values."
        empty_count = 0
        for dict_entry in list(home_sup_dat.keys()):
            if len(home_sup_dat[dict_entry]) < (33) or (len(dict_entry) <
                    self.mat_size[0]*self.mat_size[1]):
                empty_count += 1
                del home_sup_dat[dict_entry]
        if self.verbose: print "Empty value check results: {} rogue entries found".format(
                empty_count)
        
        #Targets in the mat frame        
        home_sup_pressure_map = home_sup_dat.keys()[0]        
        home_sup_joint_pos_world = np.array(home_sup_dat[home_sup_pressure_map]).reshape(
                len(home_sup_dat[home_sup_pressure_map])/3,3) # N x 3
        home_sup_joint_pos = self.world_to_mat(home_sup_joint_pos_world) # N x 3

        self.split_matrices, self.split_targets = \
                                    self.preprocess_home_position(\
                                    home_sup_pressure_map, home_sup_joint_pos)

        ## self.pca_transformation_sup(home_sup_pressure_map, home_sup_joint_pos)
        

    def preprocess_home_position(self, p_map_flat, target):
        '''Performs PCA on binarized pressure map, rotates and translates
        pressure map by principal axis. Then rotates and translates target
        values by same amount in the frame of the mat. Finally slices the home
        position pressure map into 6 regions and returns sliced matrices'''
        #Reshape to create 2D pressure map
        orig_p_map = np.asarray(np.reshape(p_map_flat, self.mat_size))
        orig_targets = target

        #Perform PCA on the pressure map to rotate and translate it to a known
        #value
        rotated_p_map = self.rotate_taxel_space(orig_p_map)
        #Perform PCA on the 3D target values to rotate and translate the 
        #targets
        rotated_targets = self.rotate_3D_space(orig_targets)

        ## self.visualize_pressure_map_slice(p_map_flat, rotated_p_map,
        ##         rotated_p_map, targets_raw=orig_targets, rotated_targets=rotated_targets)
        
        # mat to non-descrete taxel space
        rotated_targets_pixels = self.mat_to_taxels(rotated_targets)
        rotated_target_coord = np.hstack([-rotated_targets_pixels[:,1:2] + (NUMOFTAXELS_X - 1.0), 
                                          rotated_targets_pixels[:,0:1] ])
        rotated_target_coord = np.hstack([rotated_target_coord, orig_targets[:,2:3]]) #  added z axis info
        
        #Slice up the pressure map values from rotated target values projected
        #in the taxel space
        [p_map_slices, target_slices] = (
                                self.slice_pressure_map(rotated_target_coord))
        return p_map_slices, target_slices


    def rotate_3D_space(self, target):
        ''' Rotate the 3D target values (the 3D position of the markers
        attached to subject) using PCA'''
        
        #We need only X,Y coordinates in the mat frame
        targets_mat = target[:,:2]

        #The output of PCA needs rotation by -90 
        rot_targets_mat = self.pca_pixels.transform(targets_mat/INTER_SENSOR_DISTANCE)*INTER_SENSOR_DISTANCE
        rot_targets_mat = np.dot(rot_targets_mat, np.array([[0., -1.],[-1., 0.]])) 

        #Translate the targets to the center of the mat so that they match the 
        #pressure map
        rot_targets_mat += INTER_SENSOR_DISTANCE*np.array([float(NUMOFTAXELS_Y)/2.0 - self.y_offset, \
                                                           float(NUMOFTAXELS_X)/2.0 - self.x_offset])

        return rot_targets_mat


    def rotate_taxel_space(self, p_map):
        '''Rotates pressure map given to it using PCA and translates it back to 
        center of the pressure mat.'''
        #Get the nonzero indices
        nzero_indices = np.nonzero(p_map)
        #Perform PCA on the non-zero elements of the pressure map
        pca_x_tuples = zip(nzero_indices[1], 
                                    nzero_indices[0]*(-1) + (NUMOFTAXELS_X-1))
        pca_x_pixels = np.asarray([list(elem) for elem in pca_x_tuples])
        pca_y_pixels = [p_map[elem] for elem in zip(nzero_indices[0],
            nzero_indices[1])]

        #Perform PCA in the space of pressure mat pixels
        self.pca_pixels = PCA(n_components=2)
        self.pca_pixels.fit(pca_x_pixels)
        #The output of PCA needs rotation by -90 
        rot_x_pixels = self.pca_pixels.transform(pca_x_pixels)
        rot_x_pixels = np.dot(rot_x_pixels, np.array([[0., -1.],[-1., 0.]]))

        # Daehyung: Adjust the center using the existence of real value pixels
        min_y     = 1000
        max_y     = 0
        min_x     = 1000
        max_x     = 0
        min_pressure = 0.3
        for i in xrange(len(rot_x_pixels)):

            if rot_x_pixels[i][0] < min_y and pca_y_pixels[i] > min_pressure:
                min_y = rot_x_pixels[i][0]
            if rot_x_pixels[i][0] > max_y and pca_y_pixels[i] > min_pressure:
                max_y = rot_x_pixels[i][0]
            if rot_x_pixels[i][1] < min_x and pca_y_pixels[i] > min_pressure:
                min_x = rot_x_pixels[i][1]
            if rot_x_pixels[i][1] > max_x and pca_y_pixels[i] > min_pressure:
                max_x = rot_x_pixels[i][1]
                
        self.y_offset = (max_y + min_y)/2.0
        self.x_offset = (max_x + min_x)/2.0
            
        rot_trans_x_pixels = np.asarray(
            [np.asarray(elem) + np.array([NUMOFTAXELS_Y/2. - self.y_offset, \
                                          NUMOFTAXELS_X/2. - self.x_offset]) 
             for elem in rot_x_pixels]) 
        
        # Convert the continuous pixel location into integer format
        rot_trans_x_pixels = np.rint(rot_trans_x_pixels)
        
        #Thresholding the rotated matrices
        rot_trans_x_pixels[rot_trans_x_pixels < LOW_TAXEL_THRESH_X] = (
                                                 LOW_TAXEL_THRESH_X)            
        rot_trans_x_pixels[rot_trans_x_pixels[:, 1] >= NUMOFTAXELS_X] = (
                                                            NUMOFTAXELS_X - 1)

        rot_trans_x_pixels[rot_trans_x_pixels[:, 0] >= NUMOFTAXELS_Y] = (
                                                            NUMOFTAXELS_Y - 1)

        rotated_p_map_coord = ([tuple([(-1)*(elem[1] - (NUMOFTAXELS_X - 1)), 
                                    elem[0]]) for elem in rot_trans_x_pixels])
        #Creating rotated p_map
        rotated_p_map = np.zeros([NUMOFTAXELS_X, NUMOFTAXELS_Y])
        for i in range(len(pca_y_pixels)):
            rotated_p_map[rotated_p_map_coord[i]] = pca_y_pixels[i]
        return rotated_p_map


    def slice_pressure_map(self, coord):        
        '''Slices Pressure map and coordinates into parts.
        1. Head Part
        2. Right Hand
        3. Left Hand
        4. Right Leg
        5. Left Leg
        Returns: Image Templates that are then multiplied to pressure map
        to produce better output.
        '''
        limb_dict = {'head':0, 
                    'r_shoulder':1, 'l_shoulder':2, 
                    'r_elbow':3, 'l_elbow':4,
                    'r_hand':5, 'l_hand':6,
                    'r_knee':7, 'l_knee':8,
                    'r_ankle':9, 'l_ankle':10}

        #Choose the lowest(max) between the left and right hand
        upper_lower_torso_cut = np.rint(max(coord[limb_dict['l_hand'],0],
                                        coord[limb_dict['r_hand'],0]) + 5)

        left_right_side_cut =  np.rint(NUMOFTAXELS_Y/2.)
        torso_offset_horz = ([np.rint(NUMOFTAXELS_X/2.),
                                                        upper_lower_torso_cut]) 
        torso_offset_vert = np.rint(np.array([coord[limb_dict['r_hand'],1] + 3, 
                                      coord[limb_dict['l_hand'],1] - 3]))
        #Central line is through the torso
        #left_right_side_cut =  rotated_target_coord[1][1]
        left_right_side_cut =  np.rint(NUMOFTAXELS_Y/2.)
        #Cut 3 pixels below the head marker
        head_horz_cut = np.rint(min(coord[limb_dict['r_shoulder'],0], 
                                    coord[limb_dict['l_shoulder'],0]) - 2 )
        head_vert_cut = np.rint(np.array([coord[limb_dict['r_shoulder'],1] + 2 ,
                                          coord[limb_dict['l_shoulder'],1] - 2]))
        template_image = np.zeros(self.mat_size)
        template_target = np.zeros(np.shape(coord))
        
        #Head Slice 
        slice_0 = np.copy(template_image)
        target_slice_0 = np.copy(template_target)
        slice_0[:head_horz_cut, head_vert_cut[0]:head_vert_cut[1]] = 1.0 
        target_slice_0[limb_dict['head']] += 1.0         
        #Right Arm Slice 
        slice_1 = np.copy(template_image)
        target_slice_1 = np.copy(template_target)
        slice_1[:upper_lower_torso_cut, :left_right_side_cut] = 1.0
        slice_1[:head_horz_cut, head_vert_cut[0]:left_right_side_cut] = 0
        (slice_1[torso_offset_horz[0]:torso_offset_horz[1],
                torso_offset_vert[0]:torso_offset_vert[1]]) = 0
        #target_slice_1[1] = target_slice_1[1] + 1.0 
        target_slice_1[limb_dict['r_shoulder']] += 1.0
        target_slice_1[limb_dict['r_elbow']] += 1.0
        target_slice_1[limb_dict['r_hand']] += 1.0
        #Left Arm Slice 
        slice_2 = np.copy(template_image)
        target_slice_2 = np.copy(template_target)
        slice_2[:upper_lower_torso_cut, left_right_side_cut:] = 1.0
        slice_2[:head_horz_cut, left_right_side_cut:head_vert_cut[1]] = 0
        (slice_2[torso_offset_horz[0]:torso_offset_horz[1],
                torso_offset_vert[0]:torso_offset_vert[1]]) = 0
        target_slice_2[limb_dict['l_shoulder']] += 1.0
        target_slice_2[limb_dict['l_elbow']] += 1.0
        target_slice_2[limb_dict['l_hand']] += 1.0
        #Right leg Slice 
        slice_3 = np.copy(template_image)
        target_slice_3 = np.copy(template_target)
        slice_3[upper_lower_torso_cut:, :left_right_side_cut] = 1.0
        (slice_3[torso_offset_horz[0]:torso_offset_horz[1],
                torso_offset_vert[0]:left_right_side_cut]) = 1.0
        target_slice_3[limb_dict['r_knee']] += 1.0
        target_slice_3[limb_dict['r_ankle']] += 1.0
        #Left leg Slice 
        slice_4 = np.copy(template_image)
        target_slice_4 = np.copy(template_target)       
        slice_4[upper_lower_torso_cut:, left_right_side_cut:] = 1.0
        (slice_4[torso_offset_horz[0]:torso_offset_horz[1],
                left_right_side_cut:torso_offset_vert[1]]) = 1.0
        target_slice_4[limb_dict['l_knee']] += 1.0
        target_slice_4[limb_dict['l_ankle']] += 1.0

        image_slices = [slice_0, slice_1, slice_2, slice_3, slice_4]
        target_slices = ([target_slice_0, 
                          target_slice_1, 
                          target_slice_2, 
                          target_slice_3, 
                          target_slice_4])
        return image_slices, target_slices



    def preprocess_targets(self, targets):
        '''Converts the target values from a single list to a list of lists'''
        output = []
        index = 0
        while index <= (len(targets)-3):
            output.append([targets[index], targets[index+1], targets[index+2]])
            index += 3
        return output


    def world_to_mat(self, w_data):
        '''Converts a vector in the world frame to a vector in the map frame.
        Depends on the calibration of the MoCap room. Be sure to change this 
        when the calibration file changes. This function mainly helps in
        visualizing the joint coordinates on the pressure mat.
        Input: w_data: which is a 3 x 1 vector in the world frame'''
        #The homogenous transformation matrix from world to mat
        #O_m_w = np.matrix([[-1, 0, 0], [0, -1, 0], [0, 0, 1]])
        O_m_w = np.matrix(np.reshape(self.R_world_mat, (3, 3)))
        p_mat_world = O_m_w.dot(-np.asarray(self.p_world_mat))
        B_m_w = np.concatenate((O_m_w, p_mat_world.T), axis=1)
        last_row = np.array([[0, 0, 0, 1]])
        B_m_w = np.concatenate((B_m_w, last_row), axis=0)

        w_data = np.hstack([w_data, np.ones([len(w_data),1])])
        
        #Convert input to the mat frame vector
        m_data = B_m_w * w_data.T

        return m_data[:3,:].T


    def mat_to_taxels(self, m_data):
        ''' 
        Input:  Nx2 array 
        Output: Nx2 array
        '''       
        #Convert coordinates in 3D space in the mat frame into taxels
        taxels = m_data / INTER_SENSOR_DISTANCE
        
        '''Typecast into int, so that we can highlight the right taxel 
        in the pressure matrix, and threshold the resulting values'''
        taxels = np.rint(taxels)

        #Thresholding the taxels_* array
        for i, taxel in enumerate(taxels):
            if taxel[1] < LOW_TAXEL_THRESH_X: taxels[i,1] = LOW_TAXEL_THRESH_X
            if taxel[0] < LOW_TAXEL_THRESH_Y: taxels[i,0] = LOW_TAXEL_THRESH_Y
            if taxel[1] > HIGH_TAXEL_THRESH_X: taxels[i,1] = HIGH_TAXEL_THRESH_X
            if taxel[0] > HIGH_TAXEL_THRESH_Y: taxels[i,0] = HIGH_TAXEL_THRESH_Y
        return taxels


    def visualize_pressure_map(self, pressure_map_matrix, rotated_targets=None, fileNumber=0, plot_3d=False):
        '''Visualizing a plot of the pressure map'''        
        fig = plt.figure()
                 
        if plot_3d == False:            
            plt.imshow(pressure_map_matrix, interpolation='nearest', cmap=
                plt.cm.bwr, origin='upper', vmin=0, vmax=100)
        else:
            ax1= fig.add_subplot(121, projection='3d')
            ax2= fig.add_subplot(122, projection='3d')
   
            n,m = np.shape(pressure_map_matrix)
            X,Y = np.meshgrid(range(m), range(n))
            ax1.contourf(X,Y,pressure_map_matrix, zdir='z', offset=0.0, cmap=plt.cm.bwr)
            ax2.contourf(X,Y,pressure_map_matrix, zdir='z', offset=0.0, cmap=plt.cm.bwr)

        if rotated_targets is not None:
            
            rotated_target_coord = rotated_targets[:,:2]/INTER_SENSOR_DISTANCE            
            rotated_target_coord[:,1] -= (NUMOFTAXELS_X - 1)
            rotated_target_coord[:,1] *= -1.0                       

            xlim = [-10.0, 35.0]
            ylim = [70.0, -10.0]                     
            
            if plot_3d == False:
                plt.plot(rotated_target_coord[:,0], rotated_target_coord[:,1],\
                         'y*', ms=10)
                plt.xlim(xlim)
                plt.ylim(ylim)                         
            else:
                ax1.plot(np.squeeze(rotated_target_coord[:,0]), \
                         np.squeeze(rotated_target_coord[:,1]),\
                         np.squeeze(rotated_targets[:,2]), 'y*', ms=10)
                ax1.set_xlim(xlim)
                ax1.set_ylim(ylim)
                ax1.view_init(20,-30)

                ax2.plot(np.squeeze(rotated_target_coord[:,0]), \
                         np.squeeze(rotated_target_coord[:,1]),\
                         np.squeeze(rotated_targets[:,2]), 'y*', ms=10)
                ax2.view_init(1,10)
                ax2.set_xlim(xlim)
                ax2.set_ylim(ylim)
                ax2.set_zlim([-0.1,0.4])

                     
                        
        if self.save_pdf == True: 
            print "Visualized pressure map ", fileNumber
            fig.savefig('test_'+str(fileNumber)+'.png')
            os.system('mv test*.p* ~/Dropbox/HRL/') # only for Daehyung
            plt.close()
        else:
            plt.show()
        
        return

    def visualize_pressure_map_slice(self, p_map_raw, rotated_p_map, sliced_p_map, \
                                     targets_raw=None, rotated_targets=None, sliced_targets=None, \
                                     fileNumber=0):
        p_map = np.asarray(np.reshape(p_map_raw, self.mat_size))
        fig = plt.figure()

        # set options
        ax1 = fig.add_subplot(1, 3, 1)
        ax2 = fig.add_subplot(1, 3, 2)
        ax3 = fig.add_subplot(1, 3, 3)

        xlim = [-10.0, 35.0]
        ylim = [70.0, -10.0]
        ax1.set_xlim(xlim)
        ax2.set_xlim(xlim)
        ax3.set_xlim(xlim)
        ax1.set_ylim(ylim)
        ax2.set_ylim(ylim)
        ax3.set_ylim(ylim)
        
        # background
        ax1.set_axis_bgcolor('cyan')
        ax2.set_axis_bgcolor('cyan')
        ax3.set_axis_bgcolor('cyan')
        
        # Visualize pressure maps
        ax1.imshow(p_map, interpolation='nearest', cmap=
                   plt.cm.bwr, origin='upper', vmin=0, vmax=100)
        ax2.imshow(rotated_p_map, interpolation='nearest', cmap=
                        plt.cm.bwr, origin='upper', vmin=0, vmax=100)        
        ax3.imshow(sliced_p_map, interpolation='nearest', cmap=
                        plt.cm.bwr, origin='upper', vmin=0, vmax=100)

        # Visualize targets
        if targets_raw is not None:
            if type(targets_raw) == list:
                targets_raw = np.array(targets_raw)
            if len(np.shape(targets_raw))==1:
                targets_raw = np.reshape(targets_raw, (len(targets_raw)/3,3))

            target_coord = targets_raw[:,:2]/INTER_SENSOR_DISTANCE
            target_coord[:,1] -= (NUMOFTAXELS_X - 1)
            target_coord[:,1] *= -1.0                                   
            ax1.plot(target_coord[:,0], target_coord[:,1], 'y*', ms=8)
            
        if rotated_targets is not None:

            rotated_target_coord = rotated_targets[:,:2]/INTER_SENSOR_DISTANCE            
            rotated_target_coord[:,1] -= (NUMOFTAXELS_X - 1)
            rotated_target_coord[:,1] *= -1.0                       
            ax2.plot(rotated_target_coord[:,0], rotated_target_coord[:,1],\
                     'y*', ms=10)

        ## if sliced_targets is not None:
        ##     print "under construction"
                        
            
        if self.save_pdf == True: 
            print "Visualized pressure map ", fileNumber                                        
            fig.savefig('test_'+str(fileNumber)+'.pdf')
            os.system('mv test*.p* ~/Dropbox/HRL/') # only for Daehyung
            plt.close()
        else:
            plt.show()

        return
        
    ## def getOffset(self, target_mat, p_map, plot=False):
    ##     '''Find the best angular and translation offset''' 

    ##     iteration   = 500
    ##     ang_offset  = 0.0
    ##     ang_range   = [0.0, 10.0/180.0*np.pi]
    ##     x_range     = [0.0, 0.15]
    ##     y_range     = [0.0, 0.15]
    ##     max_score   = 0.
    ##     min_variance = 1000.0
    ##     best_offset = np.array([0.,0.,0.]) #ang, x, y
    ##     window_size = 3

    ##     map_pressure_thres = 10.0
    ##     head_pixel_range  = [0,10]
    ##     ankle_pixel_range = [-5,-0]
        
    ##     # get head and food parts in map
    ##     part_map = np.zeros(np.shape(p_map))
    ##     for i in xrange(len(p_map)):
    ##         for j in xrange(len(p_map[i])):
    ##             if i>=head_pixel_range[0] and i<=head_pixel_range[1] and \
    ##               p_map[i,j] > map_pressure_thres:
    ##                 part_map[i,j] = 50.0
    ##             if i>len(p_map)+ankle_pixel_range[0] and i < len(p_map)+ankle_pixel_range[1] \
    ##               and p_map[i,j] > map_pressure_thres:
    ##                 part_map[i,j] = 50.0        
    ##     ## part_map[0:13,:] = p_map[0:13,:]
    ##     ## part_map[-5:-1,:] = p_map[-5:-1,:]
    ##     #p_map = part_map        
    ##     if plot: self.visualize_pressure_map(p_map)
        
    ##     # Q: p_map is not normalized and scale is really different
    ##     while iteration>0:
    ##         iteration = iteration - 1

    ##         # random angle
    ##         ang = random.uniform(ang_range[0], ang_range[1])
    ##         x   = random.uniform(x_range[0], x_range[1])
    ##         y   = random.uniform(y_range[0], y_range[1])

    ##         # rotate target mat
    ##         rot_trans_targets_mat = np.dot(target_mat,
    ##                                        np.array([[np.cos(ang), -np.sin(ang)],
    ##                                                  [np.sin(ang), np.cos(ang)]]))        
    ##         ## print np.shape(rot_trans_targets_mat), rot_trans_targets_mat[0]
    ##         rot_trans_targets_mat = rot_trans_targets_mat + np.array([x,y])

    ##         rot_trans_targets_pixels = self.mat_to_taxels(rot_trans_targets_mat)            
    ##         rotated_target_coord = np.hstack([-rot_trans_targets_pixels[:,1:2] + (NUMOFTAXELS_X - 1), 
    ##                                           rot_trans_targets_pixels[:,0:1]])
            
    ##         ## rotated_target_coord = ([tuple([(-1)*(elem[1] - (NUMOFTAXELS_X - 1)), 
    ##         ##                             elem[0]]) for elem in rot_trans_targets_pixels])
                           
    ##         # sum of scores
    ##         score = self.pressure_score_in_window(p_map, rotated_target_coord[0], window_size) +\
    ##           self.pressure_score_in_window(p_map, rotated_target_coord[-2], window_size) +\
    ##           self.pressure_score_in_window(p_map, rotated_target_coord[-1], window_size)
              
    ##         ## print iteration, " : ", score
    ##         if score[0] > max_score or (score[0] == max_score and score[1] < min_variance):
    ##             max_score    = score[0]
    ##             min_variance = score[1]
    ##             best_offset[0] = ang
    ##             best_offset[1] = x
    ##             best_offset[2] = y

    ##     print "Best offset (ang, x, y) is ", best_offset, " with score ", max_score, min_variance
    
    ##     # get the best angular offset
    ##     return best_offset[0], best_offset[1:]


    def pressure_score_in_window(self, p_map, idx, window_size):

        n = idx[0]
        m = idx[1]

        l = 1
        if window_size%2 == 0:
            l = window_size/2
        else:
            l = (window_size-1)/2

        count = 0
        score_l  = []
        for i in range(n-l, n+l+1):
            for j in range(m-l, m+l+1):
                if i >=0 and i<len(p_map) and j>=0 and j<len(p_map[0]):

                    x = n-i
                    y = m-j
                    dist = float(2.0*window_size -x -y)/float(2.0*window_size) 
                    #np.sqrt(float(x*x+y*y))
                    score_l.append(p_map[i,j] * dist)
                    count = count + 1

        return np.array([np.mean(score_l), np.std(score_l)])
        

    def pca_transformation_sup(self, p_map_raw, target_raw):
        '''Perform PCA and any additional rotations and translations that we 
        made to the home image'''

        # map translation and rotation ------------------------------------------------
        #Reshape to create 2D pressure map
        p_map = np.asarray(np.reshape(p_map_raw, self.mat_size))
        #Get the nonzero indices
        nzero_indices = np.nonzero(p_map)
        #Perform PCA on the non-zero elements of the pressure map
        pca_x_tuples = zip(nzero_indices[1], 
                                    nzero_indices[0]*(-1) + (NUMOFTAXELS_X-1))
        pca_x_pixels = np.asarray([list(elem) for elem in pca_x_tuples])
        pca_y_pixels = [p_map[elem] for elem in zip(nzero_indices[0],
            nzero_indices[1])]

        #The output of PCA needs rotation by -90 
        rot_x_pixels = self.pca_pixels.transform(pca_x_pixels)
        rot_x_pixels = np.dot(np.asarray(rot_x_pixels),
                              np.array([[0., -1.],[-1., 0.]]))
        rot_trans_x_pixels = np.asarray(
                [np.asarray(elem) + np.array([NUMOFTAXELS_Y/2 - self.y_offset, \
                                              NUMOFTAXELS_X/2 - self.x_offset]) 
                for elem in rot_x_pixels]) 
        rot_trans_x_pixels = np.rint(rot_trans_x_pixels)
        #Thresholding the rotated matrices
        rot_trans_x_pixels[rot_trans_x_pixels < LOW_TAXEL_THRESH_X] = (
                                                 LOW_TAXEL_THRESH_X)            
        rot_trans_x_pixels[rot_trans_x_pixels[:, 1] >= NUMOFTAXELS_X] = (
                                                            NUMOFTAXELS_X - 1)

        rot_trans_x_pixels[rot_trans_x_pixels[:, 0] >= NUMOFTAXELS_Y] = (
                                                            NUMOFTAXELS_Y - 1)

        rotated_p_map_coord = ([tuple([(-1)*(elem[1] - (NUMOFTAXELS_X - 1)), 
                                    elem[0]]) for elem in rot_trans_x_pixels])
        #Creating rotated p_map
        rotated_p_map = np.zeros([NUMOFTAXELS_X, NUMOFTAXELS_Y])
        for i in range(len(pca_y_pixels)):
            rotated_p_map[rotated_p_map_coord[i]] = pca_y_pixels[i]
            
        # target translation and rotation ---------------------------------------------
        target_raw = np.array(target_raw).reshape(len(target_raw)/3,3)
        target_mat = self.world_to_mat(target_raw)

        #We need only X,Y coordinates in the mat frame
        targets_mat = target_mat[:,:2]
        
        #The output of PCA needs rotation by -90 
        rot_targets_mat = self.pca_pixels.transform(targets_mat/INTER_SENSOR_DISTANCE)*INTER_SENSOR_DISTANCE
        rot_targets_mat = np.dot(rot_targets_mat, np.array([[0., -1.],[-1., 0.]]))
        rot_trans_targets_mat = rot_targets_mat + \
            INTER_SENSOR_DISTANCE*np.array([float(NUMOFTAXELS_Y/2. - self.y_offset),\
                                            float(NUMOFTAXELS_X/2. - self.x_offset)])         
        transformed_target = np.hstack([rot_trans_targets_mat, target_raw[:,2:3]])

        ## print rot_trans_targets_mat
        ## rot_trans_targets_pixels = self.mat_to_taxels(transformed_target)
        ## rotated_target_coord = np.hstack([-rot_trans_targets_pixels[:,1:2] +\
        ##                                   (NUMOFTAXELS_X - 1.0), 
        ##                                   rot_trans_targets_pixels[:,0:1]])        

        self.visualize_pressure_map_slice(p_map_raw, rotated_p_map,
                rotated_p_map, targets_raw=target_mat, rotated_targets=transformed_target)
        
        ## self.visualize_pressure_map(rotated_p_map)
        #plt.show()
        return rotated_p_map, transformed_target
        
    def run(self):
        '''Uses the Rotation, translation, and slices obtained in
        initialization to create a synthetic database of images and ground 
        truth values'''
        home_sup = pkl.load(
                open(os.path.join(self.training_dump_path,'home_sup.p'), "rb")) 
        head_sup = pkl.load(
                open(os.path.join(self.training_dump_path,'head_sup.p'), "rb")) 
        RH_sup = pkl.load(
                open(os.path.join(self.training_dump_path,'RH_sup.p'), "rb")) 
        LH_sup = pkl.load(
                open(os.path.join(self.training_dump_path,'LH_sup.p'), "rb")) 
        RL_sup = pkl.load(
                open(os.path.join(self.training_dump_path,'RL_sup.p'), "rb")) 
        LL_sup = pkl.load(
                open(os.path.join(self.training_dump_path,'LL_sup.p'), "rb")) 
        try:
            del home_sup['mat_o']
            del head_sup['mat_o']
            del RH_sup['mat_o']
            del LH_sup['mat_o']
            del RL_sup['mat_o']
            del LL_sup['mat_o']
        except KeyError:
            pass
        #Slice each image using the slices computed earlier
        head_sliced = {}
        RH_sliced = {}
        LH_sliced = {}
        RL_sliced = {}
        LL_sliced = {}

        ## count = 0                
        # map_raw: pressure map
        # target_raw: marker, Nx3 array
        p_map_raw = home_sup.keys()[0]
        target_raw = home_sup[p_map_raw]
        [rotated_p_map, rotated_target] = self.pca_transformation_sup(
                                    p_map_raw, target_raw)

        sliced_p_map = np.multiply(rotated_p_map,
                self.split_matrices[0])
        sliced_target = np.multiply(rotated_target,
                self.split_targets[0])
        head_sliced[tuple(sliced_p_map.flatten())] = sliced_target
        sliced_p_map = np.multiply(rotated_p_map,
                self.split_matrices[1])
        sliced_target = np.multiply(rotated_target,
                self.split_targets[1])
        RH_sliced[tuple(sliced_p_map.flatten())] = sliced_target
        sliced_p_map = np.multiply(rotated_p_map,
                self.split_matrices[2])
        sliced_target = np.multiply(rotated_target,
                self.split_targets[2])
        LH_sliced[tuple(sliced_p_map.flatten())] = sliced_target
        sliced_p_map = np.multiply(rotated_p_map,
                self.split_matrices[3])
        sliced_target = np.multiply(rotated_target,
                self.split_targets[3])
        RL_sliced[tuple(sliced_p_map.flatten())] = sliced_target
        sliced_p_map = np.multiply(rotated_p_map,
                self.split_matrices[4])
        sliced_target = np.multiply(rotated_target,
                self.split_targets[4])
        LL_sliced[tuple(sliced_p_map.flatten())] = sliced_target

        for p_map_raw in head_sup.keys():
                target_raw = head_sup[p_map_raw]
                [rotated_p_map, rotated_target] = self.pca_transformation_sup(
                                            p_map_raw, target_raw)
                sliced_p_map = np.multiply(rotated_p_map,
                        self.split_matrices[0])
                sliced_target = np.multiply(rotated_target,
                        self.split_targets[0])
                head_sliced[tuple(sliced_p_map.flatten())] = sliced_target
                
        for p_map_raw in RH_sup.keys():
                target_raw = RH_sup[p_map_raw]
                [rotated_p_map, rotated_target] = self.pca_transformation_sup(
                                            p_map_raw, target_raw)
                sliced_p_map = np.multiply(rotated_p_map,
                        self.split_matrices[1])
                sliced_target = np.multiply(rotated_target,
                        self.split_targets[1])
                RH_sliced[tuple(sliced_p_map.flatten())] = sliced_target

                ## self.visualize_pressure_map(rotated_p_map, rotated_targets=rotated_target)
                ## self.visualize_pressure_map_slice(p_map_raw, rotated_p_map, sliced_p_map, \
                ##                                   targets_raw=target_raw, \
                ##                                   rotated_targets=rotated_target, \
                ##                                   sliced_targets=sliced_target)
                
        for p_map_raw in LH_sup.keys():
                target_raw = LH_sup[p_map_raw]
                [rotated_p_map, rotated_target] = self.pca_transformation_sup(
                                            p_map_raw, target_raw)
                sliced_p_map = np.multiply(rotated_p_map,
                        self.split_matrices[2])
                sliced_target = np.multiply(rotated_target,
                        self.split_targets[2])
                LH_sliced[tuple(sliced_p_map.flatten())] = sliced_target
                self.visualize_pressure_map(rotated_p_map, rotated_targets=rotated_target)

        for i, p_map_raw in enumerate(LL_sup.keys()):
                target_raw = LL_sup[p_map_raw]
                [rotated_p_map, rotated_target] = self.pca_transformation_sup(
                                            p_map_raw, target_raw)
                sliced_p_map = np.multiply(rotated_p_map,
                        self.split_matrices[4])
                sliced_target = np.multiply(rotated_target,
                        self.split_targets[4])
                LL_sliced[tuple(sliced_p_map.flatten())] = sliced_target
#                self.visualize_pressure_map(np.reshape(sliced_p_map, 
                                                                #self.mat_size))

        ## count = 0
        for p_map_raw in RL_sup.keys():
                target_raw = RL_sup[p_map_raw]
                [rotated_p_map, rotated_target] = self.pca_transformation_sup(
                                            p_map_raw, target_raw)
                sliced_p_map = np.multiply(rotated_p_map,
                        self.split_matrices[3])
                sliced_target = np.multiply(rotated_target,
                        self.split_targets[3])
                RL_sliced[tuple(sliced_p_map.flatten())] = sliced_target

                ## self.visualize_pressure_map(rotated_p_map, \
                ##                             rotated_targets=rotated_target,\
                ##                             fileNumber=count, plot_3d=True)
                ## count += 1

                
        count = 0
        final_database = {}
        for head_p_map in head_sliced.keys():
            for RH_p_map in RH_sliced.keys():
                for LH_p_map in LH_sliced.keys():
                    for RL_p_map in RL_sliced.keys():
                        for LL_p_map in LL_sliced.keys():
                            stitched_p_map = (np.asarray(head_p_map) + 
                                           np.asarray(RH_p_map) + 
                                           np.asarray(LH_p_map) + 
                                           np.asarray(RL_p_map) + 
                                           np.asarray(LL_p_map))
                            final_target = (np.asarray(head_sliced[head_p_map])+
                                            np.asarray(RH_sliced[RH_p_map]) + 
                                            np.asarray(LH_sliced[LH_p_map]) + 
                                            np.asarray(RL_sliced[RL_p_map]) +
                                            np.asarray(LL_sliced[LL_p_map]))

                            final_p_map = np.zeros(self.mat_size)                                
                            gaussian_filter(np.reshape(stitched_p_map, self.mat_size),\
                                            sigma=0.5, order=0, output=final_p_map,\
                                            mode='constant')
                            final_database[tuple(final_p_map.flatten())] = (
                                                final_target.flatten())

                            ## self.visualize_pressure_map(final_p_map, rotated_targets=final_target,\
                            ##   fileNumber=count, plot_3d=True)
                            ## if count > 20: sys.exit()
                            ## else: count += 1
                            
        ## print "Saving final_database"
        ## pkl.dump(final_database, 
        ##          open(os.path.join(self.training_dump_path,'final_database.p'), 'wb'))
        return

if __name__ == "__main__":

    import optparse
    p = optparse.OptionParser()

    p.add_option('--training_data_path', '--path',  action='store', type='string', \
                 dest='trainingPath',\
                 default='~/hrl_file_server/autobed/pose_estimation_data/subject2_stitching_test/', \
                 help='Set path to the training database.')
    p.add_option('--save_pdf', '--sp',  action='store_true', dest='save_pdf',
                 default=False, help='Save plot as a pdf.')
    p.add_option('--verbose', '--v',  action='store_true', dest='verbose',
                 default=False, help='Printout everything (under construction).')
    
    opt, args = p.parse_args()
    
    
    #Initialize trainer with a training database file
    ## training_database_pkl_directory = sys.argv[1] #  
    p = DatabaseCreator(training_database_pkl_directory=opt.trainingPath,\
                        save_pdf=opt.save_pdf,\
                        verbose=opt.verbose) 
    p.run()
    sys.exit()
