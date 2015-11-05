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
        self.final_database_path = (
        os.path.abspath(os.path.join(self.training_dump_path, os.pardir)))

        try:
            self.final_dataset = pkl.load(
                open(os.path.join(self.final_database_path,'final_database.p'), "r")) 
        except IOError:
            self.final_dataset = {}
        [self.p_world_mat, self.R_world_mat] = pkl.load(
                open(os.path.join(self.training_dump_path,'mat_axes.p'), "r"))         
        self.mat_size = (NUMOFTAXELS_X, NUMOFTAXELS_Y)
        self.individual_dataset = {} 


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

        return np.squeeze(np.asarray(m_data[:3,:].T))


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

        transformed_target = np.hstack([rot_targets_mat, target[:,2:3]])
        return transformed_target


    def rotate_taxel_space(self, p_map):
        '''Rotates pressure map given to it using PCA and translates it back to 
        center of the pressure mat.'''
        if np.shape(p_map)!=self.mat_size:
            p_map = np.asarray(np.reshape(p_map, self.mat_size))
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

        plt.show()
        
        return


    def create_raw_database(self):
        '''Creates a database using the raw pressure values(full_body) and only
        transforms world frame coordinates to mat coordinates'''
        home_sup = pkl.load(
                open(os.path.join(self.training_dump_path,'home_sup.p'), "rb")) 
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
        except KeyError:
            pass
        try:
            del RH_sup['mat_o']
        except KeyError:
            pass
        try:
            del LH_sup['mat_o']
        except KeyError:
            pass
        try:
            del RL_sup['mat_o']
        except KeyError:
            pass
        try:
            del LL_sup['mat_o']
        except KeyError:
            pass
        count = 0
        for p_map_raw in home_sup.keys():
            target_raw = home_sup[p_map_raw]
            target_raw = np.array(target_raw).reshape(len(target_raw)/3,3)
            target_mat = self.world_to_mat(target_raw)
            rot_p_map = self.rotate_taxel_space(p_map_raw)
            rot_target_mat = self.rotate_3D_space(target_mat)
            self.final_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            self.individual_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            count += 1
        for p_map_raw in LH_sup.keys():
            target_raw = LH_sup[p_map_raw]
            target_raw = np.array(target_raw).reshape(len(target_raw)/3,3)
            target_mat = self.world_to_mat(target_raw)
            rot_p_map = self.rotate_taxel_space(p_map_raw)
            rot_target_mat = self.rotate_3D_space(target_mat)
            self.final_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            self.individual_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            count += 1
        for p_map_raw in RH_sup.keys():
            target_raw = RH_sup[p_map_raw]
            target_raw = np.array(target_raw).reshape(len(target_raw)/3,3)
            target_mat = self.world_to_mat(target_raw)
            rot_p_map = self.rotate_taxel_space(p_map_raw)
            rot_target_mat = self.rotate_3D_space(target_mat)
            self.final_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            self.individual_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            count += 1
        for p_map_raw in LL_sup.keys():
            target_raw = LL_sup[p_map_raw]
            target_raw = np.array(target_raw).reshape(len(target_raw)/3,3)
            target_mat = self.world_to_mat(target_raw)
            rot_p_map = self.rotate_taxel_space(p_map_raw)
            rot_target_mat = self.rotate_3D_space(target_mat)
            self.final_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            self.individual_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            count += 1
        for p_map_raw in RH_sup.keys():
            target_raw = RH_sup[p_map_raw]
            target_raw = np.array(target_raw).reshape(len(target_raw)/3,3)
            target_mat = self.world_to_mat(target_raw)
            rot_p_map = self.rotate_taxel_space(p_map_raw)
            rot_target_mat = self.rotate_3D_space(target_mat)
            self.final_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            self.individual_dataset[tuple(rot_p_map.flatten())] = rot_target_mat.flatten()
            count += 1

        print "Saving final_dataset"
        pkl.dump(self.final_dataset, 
                  open(os.path.join(self.final_database_path,'final_database.p'), 'wb'))
        pkl.dump(self.individual_dataset,
                open(os.path.join(self.training_dump_path, 'individual_database.p'), 'wb'))
        return


    def run(self):
        '''Runs either the synthetic database creation script or the 
        raw dataset creation script to create a dataset'''
        self.create_raw_database()
        return


if __name__ == "__main__":

    import optparse
    p = optparse.OptionParser()

    p.add_option('--training_data_path', '--path',  action='store', type='string', \
                 dest='trainingPath',\
                 default='~/hrl_file_server/autobed/pose_estimation_data/subject2_stitching_test/', \
                 help='Set path to the training database.')
    
    opt, args = p.parse_args()
    
    
    #Initialize trainer with a training database file
    p = DatabaseCreator(training_database_pkl_directory=opt.trainingPath)
    p.run()
    sys.exit()
