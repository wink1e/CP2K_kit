#! /usr/env/bin python

import os
import subprocess
import numpy as np
from collections import OrderedDict
from CP2K_kit.tools import call
from CP2K_kit.tools import read_input
from CP2K_kit.tools import data_op
from CP2K_kit.tools import read_lmp
from CP2K_kit.tools import log_info
from CP2K_kit.tools import traj_info
from CP2K_kit.deepff import check_deepff
from CP2K_kit.deepff import load_data
from CP2K_kit.deepff import deepmd_run
from CP2K_kit.deepff import lammps_run
from CP2K_kit.deepff import force_eval
from CP2K_kit.deepff import cp2k_run
from CP2K_kit.deepff import sysinfo
from CP2K_kit.analyze import dp_test

def dump_input(work_dir, inp_file, f_key):

  '''
  dump_input: dump deepff input file, it will call read_input module.

  Args:
    work_dir: string
      work_dir is the working directory of CP2K_kit.
    inp_file: string
      inp_file is the deepff input file
    f_key: 1-d string list
      f_key is fixed to: ['deepmd', 'lammps', 'cp2k', 'force_eval', 'environ']
  Returns :
    deepmd_dic: dictionary
      deepmd_dic contains keywords used in deepmd.
    lammps_dic: dictionary
      lammpd_dic contains keywords used in lammps.
    cp2k_dic: dictionary
      cp2k_dic contains keywords used in cp2k.
    force_eval_dic: dictionary
      force_eval contains keywords used in force_eval.
    environ_dic: dictionary
      environ_dic contains keywords used in environment.
  '''

  job_type_param = read_input.dump_info(work_dir, inp_file, f_key)
  deepmd_dic = job_type_param[0]
  lammps_dic = job_type_param[1]
  cp2k_dic = job_type_param[2]
  force_eval_dic = job_type_param[3]
  environ_dic = job_type_param[4]

  return deepmd_dic, lammps_dic, cp2k_dic, force_eval_dic, environ_dic

def get_atoms_type(deepmd_dic):

  '''
  get_atoms_type: get atoms type for total systems

  Args:
    deepmd_dic: dictionary
      deepmd_dic contains keywords used in deepmd.
  Returns:
    tot_atoms_type_dic: dictionary
      Example: {'O':0, 'H':1}
  '''

  import linecache

  atoms_type = []
  train_dic = deepmd_dic['training']
  for key in train_dic:
    if ( 'system' in key ):
      proj_dir =  train_dic[key]['directory']
      proj_name = train_dic[key]['proj_name']
      md_coord_file = ''.join((proj_dir, '/', proj_name, '-pos-1.xyz'))
      if ( os.path.exists(md_coord_file) ):
        atoms_num, base, pre_base, frames_num, each, start_id, end_id, time_step = \
        traj_info.get_traj_info(md_coord_file, 'coord')
        atoms = []
        for i in range(atoms_num):
          line_i = linecache.getline(md_coord_file, i+3)
          line_i_split = data_op.str_split(line_i, ' ')
          atoms.append(line_i_split[0])
        linecache.clearcache()
        atoms_type.append(data_op.list_replicate(atoms))

  tot_atoms_type = data_op.list_reshape(atoms_type)
  final_atoms_type = data_op.list_replicate(tot_atoms_type)

  return final_atoms_type

def dump_init_data(work_dir, deepmd_dic, restart_iter, train_stress, tot_atoms_type_dic):

  '''
  dump_init_data: load initial training data.

  Args:
    work_dir: string
      work_dir is working directory of CP2K_kit.
    deepmd_dic: dictionary
      deepmd_dic contains keywords used in deepmd.
    restart_iter: int
      restart_iter is the iteration number of restart.
    train_stress: bool
      train_stress is whether we need to dump stress.
  Returns:
    init_train_data: 1-d string list
      init_train_data contains initial training data directories.
    init_data_num : int
      init_data_num is the number of data for initial training.
  '''

  if ( restart_iter == 0 ):
    cmd = 'rm -rf init_train_data'
    call.call_simple_shell(work_dir, cmd)

  i = 0
  init_train_data = []
  init_data_num = 0
  cmd = "mkdir %s" % ('init_train_data')
  if ( restart_iter == 0 ):
    call.call_simple_shell(work_dir, cmd)
  train_dic = deepmd_dic['training']
  if ( 'set_data_dir' in train_dic.keys() ):
    set_data_dir = train_dic['set_data_dir']
  for key in train_dic:
    if ( 'system' in key):
      save_dir = ''.join((work_dir, '/init_train_data/data_', str(i)))
      init_train_data.append(save_dir)
      if ( restart_iter == 0 ):
        init_train_key_dir = train_dic[key]['directory']
        proj_name = train_dic[key]['proj_name']
        start = train_dic[key]['start_frame']
        end = train_dic[key]['end_frame']
        choosed_num = train_dic[key]['choosed_frame_num']
        parts = train_dic[key]['set_parts']
        load_data.load_data_from_dir(init_train_key_dir, work_dir, save_dir, proj_name, start, end, choosed_num, train_stress, tot_atoms_type_dic)
        energy_array, coord_array, frc_array, box_array, virial_array = load_data.read_raw_data(save_dir)
        data_num = load_data.raw_data_to_set(parts, save_dir, energy_array, coord_array, frc_array, box_array, virial_array)
        init_data_num = init_data_num+data_num
      else:
        if ( os.path.exists(save_dir) ):
          init_data_num = 0
        else:
          log_info.log_error('%s does not exist for training system %d' %(save_dir, i))
          exit()
      i = i+1

  if 'set_data_dir' in locals():
    init_train_data.append(os.path.abspath(set_data_dir))

  return init_train_data, init_data_num

def write_active_data(work_dir, conv_iter, tot_atoms_type_dic):

  '''
  write_active_data: write the data generated by active learning.

  Args:
    work_dir: string
      work_dir is the working directory.
    conv_iter: int
      conv_iter is the number of iteration.
  Returns :
    none
  '''

  active_data_dir = ''.join((work_dir, '/active_data'))
  str_print = 'Active data is written in %s' %(active_data_dir)
  print (data_op.str_wrap(str_print, 80), flush=True)

  cmd = "mkdir %s" %('active_data')
  call.call_simple_shell(work_dir, cmd)
  cmd = "ls | grep %s" % ('sys_')
  sys_num = len(call.call_returns_shell(''.join((work_dir, '/iter_0/02.lammps_calc')), cmd))

  for i in range(sys_num):

    energy_cp2k = []
    frc_cp2k = []
    frc_x_cp2k = []
    frc_y_cp2k = []
    frc_z_cp2k = []

    sys_dir = ''.join((active_data_dir, '/sys_', str(i)))
    cmd = "mkdir %s" %(''.join(('sys_', str(i))))
    call.call_simple_shell(active_data_dir, cmd)
    energy_file_name = ''.join((sys_dir, '/energy.raw'))
    coord_file_name = ''.join((sys_dir, '/coord.raw'))
    frc_file_name = ''.join((sys_dir, '/force.raw'))
    cell_file_name = ''.join((sys_dir, '/box.raw'))
    energy_file = open(energy_file_name, 'w')
    coord_file = open(coord_file_name, 'w')
    frc_file = open(frc_file_name, 'w')
    cell_file = open(cell_file_name, 'w')

    coord_traj_file_name = ''.join((sys_dir, '/active-pos-1.xyz'))
    frc_traj_file_name = ''.join((sys_dir, '/active-frc-1.xyz'))
    cell_traj_file_name = ''.join((sys_dir, '/active-1.cell'))
    coord_traj_file = open(coord_traj_file_name, 'w')
    frc_traj_file = open(frc_traj_file_name, 'w')
    cell_traj_file = open(cell_traj_file_name, 'w')

    for j in range(conv_iter):
      iter_dir = ''.join((work_dir, '/iter_', str(j)))
      data_dir = ''.join((iter_dir, '/03.cp2k_calc/sys_', str(i), '/data'))
      energy_array, coord_array, frc_array, cell_array, virial_array = load_data.read_raw_data(data_dir)
      frames_num = len(energy_array)
      atoms_num = int(len(coord_array[0])/3)
      for k in range(frames_num):
        energy_file.write('%f\n' %(energy_array[k]))
        energy_cp2k.append(energy_array[k])
        frame_str = ''
        for l in range(len(coord_array[k])):
          if ( l == 0 ):
            frame_str = ''.join((frame_str, str(coord_array[k][l])))
          else:
            frame_str = ' '.join((frame_str, str(coord_array[k][l])))
        coord_file.write('%s\n' %(frame_str))

        frc_cp2k_k = []
        frc_x_cp2k_k = []
        frc_y_cp2k_k = []
        frc_z_cp2k_k = []

        frame_str = ''
        for l in range(len(frc_array[k])):
          if ( l == 0 ):
            frame_str = ''.join((frame_str, str(frc_array[k][l])))
          else:
            frame_str = ' '.join((frame_str, str(frc_array[k][l])))
          frc_cp2k_k.append(frc_array[k][l])
          if ( l%3 == 0 ):
            frc_x_cp2k_k.append(frc_array[k][l])
          elif ( l%3 == 1 ):
            frc_y_cp2k_k.append(frc_array[k][l])
          elif ( l%3 == 2 ):
            frc_z_cp2k_k.append(frc_array[k][l])
        frc_cp2k.append(frc_cp2k_k)
        frc_x_cp2k.append(frc_x_cp2k_k)
        frc_y_cp2k.append(frc_y_cp2k_k)
        frc_z_cp2k.append(frc_z_cp2k_k)
        frc_file.write('%s\n' %(frame_str))

        frame_str = ''
        for l in range(len(cell_array[k])):
          if ( l == 0 ):
            frame_str = ''.join((frame_str, str(cell_array[k][l])))
          else:
            frame_str = ' '.join((frame_str, str(cell_array[k][l])))
        cell_file.write('%s\n' %(frame_str))
    energy_file.close()
    coord_file.close()
    frc_file.close()
    cell_file.close()

    energy_array, coord_array, frc_array, cell_array, virial_array = load_data.read_raw_data(sys_dir)
    load_data.raw_data_to_set(1, sys_dir, energy_array, coord_array, frc_array, cell_array, virial_array)

    atoms = []
    type_raw = open(''.join((sys_dir, '/type.raw')), 'rb').read().split()
    for j in range(len(type_raw)):
      atoms.append(data_op.get_dic_key(tot_atoms_type_dic, int(type_raw[j].decode())))

    cell_traj_file.write('#   Step   Time [fs]       Ax [Angstrom]       Ay [Angstrom]       Az [Angstrom]       Bx [Angstrom]       By [Angstrom]       Bz [Angstrom]       Cx [Angstrom]       Cy [Angstrom]       Cz [Angstrom]      Volume [Angstrom^3]\n')
    frames_num_tot = len(energy_array)
    for j in range(frames_num_tot):
      frc_array_j = frc_array[j].reshape(atoms_num, 3)
      coord_array_j = coord_array[j].reshape(atoms_num, 3)
      cell_array_j = cell_array[j].reshape(3,3)
      vol = np.linalg.det(cell_array_j)

      coord_traj_file.write('%8d\n' %(atoms_num))
      coord_traj_file.write('%s%9d%s%13.3f%s%21.10f\n' %(' i =', j, ', time =', j*0.5, ', E =', energy_array[j]))
      for k in range(atoms_num):
        coord_traj_file.write('%3s%21.10f%20.10f%20.10f\n' %(atoms[k], coord_array_j[k][0], coord_array_j[k][1], coord_array_j[k][2]))

      frc_traj_file.write('%8d\n' %(atoms_num))
      frc_traj_file.write('%s%9d%s%13.3f%s%21.10f\n' %(' i =', j, ', time =', j*0.5, ', E =', energy_array[j]))
      for k in range(atoms_num):
        frc_traj_file.write('%3s%21.10f%20.10f%20.10f\n' %(atoms[k], frc_array_j[k][0], frc_array_j[k][1], frc_array_j[k][2]))

      cell_traj_file.write('%8d%12.3f%20.10f%20.10f%20.10f%20.10f%20.10f%20.10f%20.10f%20.10f%20.10f%25.10f\n' \
                           %(j, j*0.5, cell_array_j[0][0], cell_array_j[0][1], cell_array_j[0][2], \
                             cell_array_j[1][0], cell_array_j[1][1], cell_array_j[1][2], \
                             cell_array_j[2][0], cell_array_j[2][1], cell_array_j[2][2], vol))

    coord_traj_file.close()
    frc_traj_file.close()
    cell_traj_file.close()

def run_iter(inp_file, deepmd_dic, lammps_dic, cp2k_dic, force_eval_dic, environ_dic, init_train_data, restart_data_num, \
             restart_stage, work_dir, max_iter, restart_iter, tot_atoms_type_dic, proc_num, host, device, usage):

  '''
  run_iter: run active learning iterations.

  Args:
    inp_file: string
      inp_file is the input file of CP2K_kit.
    deepmd_dic: dictionary
      deepmd_dic contains keywords used in deepmd.
    lammps_dic: dictionary
      lammpd_dic contains keywords used in lammps.
    cp2k_dic: dictionary
      cp2k_dic contains keywords used in cp2k.
    force_eval_dic: dictionary
      force_eval_dic contains keywords used in force_eval.
    environ_dic: dictionary
      environ_dic contains keywords used in environment.
    init_train_data: 1-d string list
      init_train_data contains initial training data directories.
    restart_data_num: int
      restart_data_num is the data number in restart step.
    restart_stage: int
      restart_stage is the stage of restart.
    work_dir: string
      work_dir is working directory of CP2K_kit.
    max_iter: int
      max_iter is the maxium iterations for active learning.
    restart_iter: int
      restart_iter is the iteration number of restart.
    proc_num: int
      proc_num is the number of processors.
    host: 1-d string list
      host is the name of host of computational nodes.
    device: 2-d string list
      device is the gpu device name for each computational node.
    usage: 2-d float list
      usage is the memory usage of gpu devices for each computational node.
  Returns:
    none
  '''

  np.random.seed(1234567890)

  numb_test = deepmd_dic['training']['numb_test']
  model_type = deepmd_dic['training']['model_type']
  neuron = deepmd_dic['training']['neuron']
  train_stress = deepmd_dic['training']['train_stress']

  conv_new_data_num = force_eval_dic['conv_new_data_num']
  choose_new_data_num_limit = force_eval_dic['choose_new_data_num_limit']
  force_conv = force_eval_dic['force_conv']

  cp2k_exe = environ_dic['cp2k_exe']
  cp2k_env_file = environ_dic['cp2k_env_file']
  parallel_exe = environ_dic['parallel_exe']
  cuda_dir = environ_dic['cuda_dir']
  cp2k_job_num = environ_dic['cp2k_job_num']
  lmp_mpi_num = environ_dic['lmp_mpi_num']
  lmp_openmp_num = environ_dic['lmp_openmp_num']

  data_num = []
  data_num.append(restart_data_num)

  for i in range(restart_iter, max_iter, 1):

    print (''.join(('iter_', str(i))).center(80,'*'), flush=True)

    #Generate iteration directory
    iter_restart = ''.join(('iter_', str(i)))
    iter_restart_dir = ''.join((work_dir, '/', iter_restart))

    if ( not os.path.exists(iter_restart_dir) ):
      cmd = "mkdir %s" % (iter_restart)
      call.call_simple_shell(work_dir, cmd)

    if ( restart_stage == 0 ):
      #Perform deepmd calculation
      print ('Step 1: deepmd-kit tasks', flush=True)

      #For different model_type, seed and neuron are different.
      if ( model_type == 'use_seed' ):
        if ( 'seed_num' in deepmd_dic['training'].keys() ):
          seed_num = int(deepmd_dic['training']['seed_num'])
        else:
          seed_num = 4
        descr_seed = []
        fit_seed = []
        tra_seed = []
        for j in range(seed_num):
          descr_seed.append(np.random.randint(10000000000))
          fit_seed.append(np.random.randint(10000000000))
          tra_seed.append(np.random.randint(10000000000))

      if ( model_type == 'use_node' ):
        descr_seed = []
        fit_seed = []
        tra_seed = []

        for j in range(len(neuron)):
          descr_seed.append(np.random.randint(10000000000))
          fit_seed.append(np.random.randint(10000000000))
          tra_seed.append(np.random.randint(10000000000))

      deepmd_run.gen_deepmd_task(deepmd_dic, work_dir, i, init_train_data, numb_test, \
                                 descr_seed, fit_seed, tra_seed, neuron, model_type, sum(data_num))
      deepmd_run.run_deepmd(work_dir, i, parallel_exe, host, device, usage, cuda_dir)
      check_deepff.write_restart_inp(inp_file, i, 1, sum(data_num), work_dir)

    if ( restart_stage == 0 or restart_stage == 1 ):
      #Perform lammps calculations
      print ('Step 2: lammps tasks', flush=True)

      lammps_run.gen_lmpmd_task(lammps_dic, work_dir, i, tot_atoms_type_dic)
      lammps_run.run_lmpmd(work_dir, i, lmp_mpi_num, lmp_openmp_num, device[0])
      check_deepff.write_restart_inp(inp_file, i, 2, sum(data_num), work_dir)

    if ( restart_stage == 0 or restart_stage == 1 or restart_stage == 2 ):
      #Perform lammps force calculations
      if ( restart_stage == 2 ):
        print ('Step 2: lammps tasks', flush=True)
      sys_num, atoms_type_dic_tot, atoms_num_tot = lammps_run.get_md_sys_info(lammps_dic, tot_atoms_type_dic)
      lammps_run.gen_lmpfrc_file(work_dir, i, atoms_num_tot, atoms_type_dic_tot)
      lammps_run.run_lmpfrc(work_dir, i, parallel_exe, proc_num, atoms_num_tot)
      check_deepff.write_restart_inp(inp_file, i, 3, sum(data_num), work_dir)

    if ( restart_stage == 0 or restart_stage == 1 or restart_stage == 2 or restart_stage == 3 ):
      #Get force-force correlation and then choose new structures
      sys_num, atoms_type_dic_tot, atoms_num_tot = lammps_run.get_md_sys_info(lammps_dic, tot_atoms_type_dic)
      struct_index, success_ratio_sys, success_ratio = force_eval.choose_lmp_str(work_dir, i, atoms_type_dic_tot, atoms_num_tot, force_conv)

      for j in range(len(success_ratio_sys)):
        print ('  The accurate ratio for system %d in iteration %d is %.2f%%' %(j, i, success_ratio_sys[j]*100), flush=True)

      print ('  The accurate ratio for whole %d systems in iteration %d is %.2f%%' %(sys_num, i, success_ratio*100), flush=True)
      choose_data_num = []
      for key1 in struct_index:
        for key2 in struct_index[key1]:
          choose_data_num.append(len(struct_index[key1][key2]))

      max_choose_data_num = max(choose_data_num)
      if ( max_choose_data_num <= conv_new_data_num ):
        print (''.center(80,'*'), flush=True)
        print ('Cheers! deepff is converged!', flush=True)
        if ( i != 0 ):
          write_active_data(work_dir, i, tot_atoms_type_dic)
        exit()

      print ('Step 3: cp2k tasks', flush=True)
      #Perform cp2k calculation
      cp2k_run.gen_cp2k_task(cp2k_dic, work_dir, i, atoms_type_dic_tot, atoms_num_tot, \
                           struct_index, conv_new_data_num, choose_new_data_num_limit, train_stress)
      cp2k_run.run_cp2kfrc(work_dir, i, cp2k_exe, parallel_exe, cp2k_env_file, cp2k_job_num, proc_num, atoms_num_tot)

      #Get new data of cp2k
      for j in range(sys_num):
        file_dir = ''.join((work_dir, '/iter_', str(i), '/03.cp2k_calc/sys_', str(j)))
        load_data.load_data_from_sepfile(file_dir, 'task_', 'cp2k', tot_atoms_type_dic)
        cp2k_data_dir = ''.join((file_dir, '/data'))
        if ( os.path.exists(cp2k_data_dir) ):
          energy_array, coord_array, frc_array, box_array, virial_array = load_data.read_raw_data(cp2k_data_dir)
          train_data_num = load_data.raw_data_to_set(1, cp2k_data_dir, energy_array, coord_array, frc_array, box_array, virial_array)
          data_num.append(train_data_num)

      print ('  Success: dump new raw data of cp2k', flush=True)
      check_deepff.write_restart_inp(inp_file, i+1, 0, sum(data_num), work_dir)
      restart_stage = 0

    if ( i == max_iter-1 ):
      log_info.log_error('Active learning does not converge')
      write_active_data(work_dir, i+1, tot_atoms_type_dic)

def kernel(work_dir, inp_file):

  '''
  kernel: kernel function to do active learning.

  Args:
    work_dir: string
      work_dir is the working directory of CP2K_kit.
    inp_file: string
      inp_file is the deepff input file
  '''

  import os
  import linecache
  import platform
  import multiprocessing

  host_file = ''.join((work_dir, '/hostname'))
  if ( os.path.exists(host_file) ):
    line_num = len(open(host_file).readlines())
    line_1 = linecache.getline(host_file, 1)
    proc_num = int(line_1.strip('\n'))
    host = []
    for i in range(line_num-1):
      line_i = linecache.getline(host_file, i+2)
      line_i_split = data_op.str_split(line_i, ' ')
      host.append(line_i_split[1].strip('\n'))
    ssh = True
  else:
    proc_num = int(multiprocessing.cpu_count()/2)
    host = [platform.node()]
    ssh = False

  linecache.clearcache()

  device, usage = sysinfo.analyze_gpu(host, ssh, work_dir)

  deepff_key = ['deepmd', 'lammps', 'cp2k', 'force_eval', 'environ']

  deepmd_dic, lammps_dic, cp2k_dic, force_eval_dic, environ_dic = \
  dump_input(work_dir, inp_file, deepff_key)

  deepmd_dic, lammps_dic, cp2k_dic, force_eval_dic, environ_dic = \
  check_deepff.check_inp(deepmd_dic, lammps_dic, cp2k_dic, force_eval_dic, environ_dic, proc_num)
  print ('Check input file: no error in %s' %(inp_file), flush=True)

  max_iter = force_eval_dic['max_iter']
  restart_iter = force_eval_dic['restart_iter']
  train_stress = deepmd_dic['training']['train_stress']

  tot_atoms_type = get_atoms_type(deepmd_dic)
  tot_atoms_type_dic = OrderedDict()
  for i in range(len(tot_atoms_type)):
    tot_atoms_type_dic[tot_atoms_type[i]] = i

  if ( deepmd_dic['model']['type_map'] != tot_atoms_type ):
    type_map_str = data_op.comb_list_2_str(tot_atoms_type, ' ')
    log_info.log_error('Input error: type_map should be %s, please reset deepff/deepmd/model/type_map' %(type_map_str))
    exit()

  init_train_data, init_data_num = dump_init_data(work_dir, deepmd_dic, restart_iter, train_stress, tot_atoms_type_dic)

  if ( restart_iter == 0 ):
    restart_data_num = init_data_num
  else:
    restart_data_num = force_eval_dic['restart_data_num']
  restart_stage = force_eval_dic['restart_stage']

  print ('Initial training data:', flush=True)
  for i in range(len(init_train_data)):
    print ('%s' %(data_op.str_wrap(init_train_data[i], 80)), flush=True)

  run_iter(inp_file, deepmd_dic, lammps_dic, cp2k_dic, force_eval_dic, environ_dic, init_train_data, restart_data_num, \
           restart_stage, work_dir, max_iter, restart_iter, tot_atoms_type_dic, proc_num, host, device, usage)

if __name__ == '__main__':

  from CP2K_kit.deepff import active
  work_dir = '/home/lujunbo/code/github/CP2K_kit/deepff/work_dir'
  inp_file = 'input.inp'
  max_cycle = 100
  active.kernel(work_dir, inp_file)
