#!/usr/bin/env python

import os
import sys
import math
import linecache
from CP2K_kit.tools import atom
from CP2K_kit.tools import list_dic_op
from CP2K_kit.tools import traj_tools

def get_traj_info(file_name, group=[], return_group=False):

  '''
  get_traj_info : get several important information of trajectory

  Args :
    file_name : string
      file_name is the name of trajectory file used to analyze.
    group : 2-d string list
      group contain the basic atom info in a set of atoms.
      Example : [['O', 'H', 'H']]
    return_group : bool
  Returns :
    blocks_num : int
      blocks_num is the number of lines in one block in trajectory file.
    base : int
      base is the number of lines before structure in a structure block.
    pre_base : int
      pre_base is the number of lines before block of trajectory file.
    frames_num : int
      frames_num is the number of frames in trajectory file.
    each : int
      each is printing frequency of md.
    start_frame_id : int
      start_frame_id is the starting frame used to choose.
    end_frame_id : int
      end_frame_id is the ending frame used to choose.
    file_start : int
      file_start is the starting frame in trajectory file.
    time_step : float
      time_step is time step of md. Its unit is fs in CP2K_kit.
    exclude_group_id : 1d int list
      exclude_group_id is the id of atoms that have no group.
    group_atom_1_id : 2d int list
      group_atom_1_id is the id of first atoms in the molecules in the group.
    group_atoms_mass : 2d float list
      group_atoms_mass contains the atoms mass for each group.
  '''

  blocks_num, pre_base, base, frame_start = traj_tools.get_block_base(file_name)

  whole_line_num_1 = len(open(file_name).readlines())

  if ((whole_line_num_1-pre_base)%(blocks_num+base) != 0):
    break_frame = traj_tools.find_breakpoint(file_name)
    print ("There is incomplete frame")
    print ("The breaking frames are",break_frame)
    sys.exit(1)
  else:
    frames_num_1 = int((whole_line_num_1-pre_base)/(blocks_num+base))

  if (".xyz" in file_name):
    if ( "-pos-" in file_name or "-vel-" in file_name or "-frc-" in file_name):
      a = linecache.getline(file_name, pre_base+2)
      b = list_dic_op.str_split(a, ' ')
      start_frame_id = int(b[2].strip(','))
      start_time = float(b[5].strip(','))
    else:
      start_frame_id = 0

    if ( whole_line_num_1 > blocks_num+base+pre_base ):
      if ( "-pos-" in file_name or "-vel-" in file_name or "-frc-" in file_name):
        a = linecache.getline(file_name, (blocks_num+base)*1+pre_base+2)
        b = list_dic_op.str_split(a, ' ')
        second_frame_id = int(b[2].strip(','))
        second_time = float(b[5].strip(','))

        a = linecache.getline(file_name, (frames_num_1-1)*(blocks_num+base)+pre_base+2)
        b = list_dic_op.str_split(a, ' ')
        end_frame_id = int(b[2].strip(','))
    else:
      end_frame_id = start_frame_id

  if (".ener" in file_name):

    a = linecache.getline(file_name, pre_base+1)
    b = list_dic_op.str_split(a, ' ')
    start_frame_id = int(b[0])
    start_time = float(b[1])

    if ( whole_line_num_1 > blocks_num+base+pre_base ):
      a = linecache.getline(file_name, (blocks_num+base)*1+pre_base+1)
      b = list_dic_op.str_split(a, ' ')
      second_frame_id = int(b[0])
      second_time = float(b[1])

      a = linecache.getline(file_name, whole_line_num_1)
      b = list_dic_op.str_split(a, ' ')
      end_frame_id = int(b[0])
    else:
      end_frame_id = start_frame_id

  if ( whole_line_num_1 > blocks_num+base+pre_base ):
    each = second_frame_id-start_frame_id
    time_step = (second_time-start_time)/each
    frames_num_2 = (end_frame_id-start_frame_id)/each+1
  else:
    frames_num_2 = 1
    time_step = 0.0
    each = 0

  if (frames_num_1 != frames_num_2):
    traj_tools.delete_duplicate(file_name)

  whole_line_num = len(open(file_name).readlines())
  frames_num = int((whole_line_num-pre_base)/(blocks_num+base))

  #For groups, we will consider the connectivity.
  if return_group:
    if (".xyz" in file_name):

      element = []
      for i in range(blocks_num):
        a = linecache.getline(file_name,i+base+1)
        b = a.split(' ')
        c = []
        for j in range(len(b)):
          if (b[j] != ''):
            c.append(b[j])
        element.append(c[0])

      exclude_group_id = []
      group_atom_1_id = []
      group_atoms_mass = []

      for i in range(blocks_num):
        exclude_group_id.append(i+1)

      for i in range(len(group)):
        group_i_atom_1_id = []
        group_i_atoms_mass = []
        all_true = [True]*len(group[i])

        for j in range(len(group[i])):
          group_i_atoms_mass.append(atom.get_atom_mass(group[i][j])[1])
        group_atoms_mass.append(group_i_atoms_mass)

        for j in range(blocks_num-len(group[i])+1):
          state = []
          for k in range(len(group[i])):
            state.append( element[j+k] == group[i][k] )
          if ( state == all_true ):
            group_i_atom_1_id.append(j+1)
        group_atom_1_id.append(group_i_atom_1_id)

        for j in range(len(group_i_atom_1_id)):
          for k in range(len(group[i])):
            exclude_group_id.remove(group_i_atom_1_id[j]+k)

  if (".xyz" in file_name):
    if return_group:
      return blocks_num, base, pre_base, frames_num, each, start_frame_id, end_frame_id, \
             time_step, exclude_group_id, group_atom_1_id, group_atoms_mass
    else:
      return blocks_num, base, pre_base, frames_num, each, start_frame_id, end_frame_id, time_step
  if (".ener" in file_name):
    return blocks_num, base, pre_base, frames_num, each, start_frame_id, end_frame_id, time_step
  if (".LagrangeMultLog" in file_name):
    return blocks_num, base, pre_base, frames_num

if __name__ == '__main__':
  from CP2K_kit.tools import traj_info
  file_name = 'test.xyz'
  groups = [['Mn','F','O','O','O']]
  blocks_num, base, pre_base, frames_num, each, start_frame_id, end_frame_id, \
  time_step, exclude_group_id, group_atom_1_id, group_atoms_num = \
  traj_info.get_traj_info(file_name, groups, True)
  print (group_atom_1_id, group_atoms_num, exclude_group_id,)

