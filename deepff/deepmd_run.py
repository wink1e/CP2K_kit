#! /usr/env/bin python

import os
import math
import json
import copy
import subprocess
import linecache
import numpy as np
from collections import OrderedDict
from CP2K_kit.tools import call
from CP2K_kit.tools import log_info
from CP2K_kit.tools import data_op
from CP2K_kit.deepff import check_deepff

def gen_deepmd_task(deepmd_dic, work_dir, iter_id, init_train_data, numb_test, \
                    descr_seed, fit_seed, tra_seed, neuron, model_type, data_num):

  '''
  gen_deepmd_task: generate deepmd tasks

  Args :
    deepmd_dic: dictionary
      deepmd_dic contains keywords used in deepmd.
    work_dir: string
      work_dir is working directory of CP2K_kit.
    iter_id: int
      iter_id is the iteration id.
    init_train_data: 1-d string list
      init_train_data contains initial training data directories.
    numb_test: int
      numb_test is number of testing data sets when run deepmd
    descr_seed: 1-d int list
      descr_seed is the seed number in descriptor part.
    fit_seed: 1-d int list
      fit_seed is the seed number in fitting part.
    tra_seed: 1-d int list
      tra_seed is the seed number in training part.
    neuron: 1-d int list or int
      neuron is the number of nodes in neural network.
    model_type: string
      model_type has two choices: 'use_seed', 'use_node'
    data_num: 1-d int list
      data_num is the numbers of training data for each system.
  Returns:
    none
  '''

  #copy should be done at first, because the following operators will change it!
  deepmd_param = copy.deepcopy(deepmd_dic)

  iter_dir = ''.join((work_dir, '/iter_', str(iter_id)))
  train_dir = ''.join(iter_dir + '/01.train')
  if ( not os.path.exists(train_dir) ):
    cmd = "mkdir %s" % ('01.train')
    call.call_simple_shell(iter_dir, cmd)

  data_dir = copy.deepcopy(init_train_data)
  final_data_dir = []
  if ( iter_id > 0 ):
    for i in range(iter_id):
      calc_dir = ''.join((work_dir, '/iter_', str(i), '/03.cp2k_calc'))
      cmd = "ls | grep %s" % ('sys_')
      sys_num = len(call.call_returns_shell(calc_dir, cmd))
      for j in range(sys_num):
        prev_data_dir = ''.join((calc_dir, '/sys_', str(j), '/data'))
        if ( os.path.exists(prev_data_dir) ):
          cmd = "ls | grep %s" % ('set.')
          set_parts = len(call.call_returns_shell(prev_data_dir, cmd))
          if ( (set_parts-1) >= 10 ):
            final_set_dir_name = 'set.0'+str(set_parts-1)
          elif ( (set_parts-1) < 10 ):
            final_set_dir_name = 'set.00'+str(set_parts-1)
          elif ( (set_parts-1) > 100 ):
            final_set_dir_name = 'set.'+str(set_parts-1)
          ene_npy_file = ''.join((prev_data_dir, '/', final_set_dir_name, '/energy.npy'))
          final_set_data_num = len(np.load(ene_npy_file))
          if ( final_set_data_num > numb_test ):
            data_dir.append(prev_data_dir)
            if ( i == iter_id-1 ):
              final_data_dir.append(prev_data_dir)

  if ( iter_id > 1 and len(final_data_dir) == 0 ):
    print (''.center(80,'*'), flush=True)
    print ('Cheers! deepff is converged!', flush=True)
    check_deepff.write_active_data(work_dir, i, tot_atoms_type_dic)
    exit()

  start_lr = deepmd_param['learning_rate']['start_lr']
  batch_size = deepmd_param['training']['batch_size']
  fix_stop_batch = deepmd_param['training']['fix_stop_batch']
  use_prev_model = deepmd_param['training']['use_prev_model']
  if not fix_stop_batch:
    epoch_num = deepmd_param['training']['epoch_num']
    stop_batch = math.ceil(epoch_num*int(sum(data_num)/batch_size)/10000)*10000
    decay_steps = math.ceil(int(sum(data_num)/batch_size)/1000)*1000
    if ( stop_batch < decay_steps*200 ):
      stop_batch = decay_steps*200
    deepmd_param['learning_rate']['decay_steps'] = decay_steps
    deepmd_param['training']['stop_batch'] = stop_batch

  deepmd_param['training']['systems'] = data_dir
  deepmd_param['training']['batch_size'] = [batch_size]*len(data_dir)

  for key in deepmd_dic['training'].keys():
    if ( 'system' in key ):
      deepmd_param['training'].pop(key)

  if ( 'seed_num' in deepmd_param['training'].keys() ):
    deepmd_param['training'].pop('seed_num')
  if ( 'epoch_num' in deepmd_param['training'].keys() ):
    deepmd_param['training'].pop('epoch_num')
  deepmd_param['training'].pop('model_type')
  deepmd_param['training'].pop('neuron')
  deepmd_param['training'].pop('shuffle_data')
  deepmd_param['training'].pop('train_stress')
  deepmd_param['training'].pop('use_prev_model')
  deepmd_param['training'].pop('fix_stop_batch')

  if ( iter_id > 0 and use_prev_model ):
    data_num_1 = data_num[0:(len(data_dir)-len(final_data_dir))]
    prob_data_num_1 = math.erf(sum(data_num_1)/sum(data_num)*2)/2**(1/iter_id)
    prob_data_num_2 = 1.0-prob_data_num_1
    deepmd_param['learning_rate']['start_lr'] = start_lr/10
    deepmd_param['training']['stop_batch'] = int(deepmd_param['training']['stop_batch']/2)
    prob_sys_1 = '0:%d:%f' %(len(data_dir)-len(final_data_dir), prob_data_num_1)
    prob_sys_2 = '%d:%d:%f' %(len(data_dir)-len(final_data_dir), len(data_dir), prob_data_num_2)
    #prob_sys_1 = '0:%d:%f' %(len(data_dir)-len(final_data_dir), 0.2)
    #prob_sys_2 = '%d:%d:%f' %(len(data_dir)-len(final_data_dir), len(data_dir), 0.8)
    auto_prob_style = data_op.comb_list_2_str(['prob_sys_size', prob_sys_1, prob_sys_2], ';')
    deepmd_param['training']['auto_prob_style'] = auto_prob_style

  if ( model_type == 'use_seed' ):
    for i in range(len(descr_seed)):
      cmd = "mkdir %s" % (str(i))
      call.call_simple_shell(train_dir, cmd)
      deepmd_param_i = copy.deepcopy(deepmd_param)
      deepmd_param_i['model']['descriptor']['seed'] = descr_seed[i]
      deepmd_param_i['model']['fitting_net']['seed'] = fit_seed[i]
      deepmd_param_i['training']['seed'] = tra_seed[i]
      deepmd_param_i['model']['fitting_net']['neuron'] = neuron
      json_str = json.dumps(deepmd_param_i, indent=4)

      with open(''.join((train_dir, '/', str(i), '/', 'input.json')), 'w') as json_file:
        json_file.write(json_str)

  elif ( model_type == 'use_node' ):
    for i in range(len(neuron)):
      model_dir = ''.join((train_dir, '/', str(i)))
      if ( not os.path.exists(model_dir) ):
        cmd = "mkdir %s" % (str(i))
        call.call_simple_shell(train_dir, cmd)
      deepmd_param_i = copy.deepcopy(deepmd_param)
      deepmd_param_i['model']['descriptor']['seed'] = descr_seed[i]
      deepmd_param_i['model']['fitting_net']['seed'] = fit_seed[i]
      deepmd_param_i['training']['seed'] = tra_seed[i]
      deepmd_param_i['model']['fitting_net']['neuron'] = neuron[i]
      json_str = json.dumps(deepmd_param_i, indent=4)

      with open(''.join((model_dir, '/input.json')), 'w') as json_file:
        json_file.write(json_str)

def deepmd_parallel(work_dir, iter_id, use_prev_model, start, end, parallel_exe, dp_path, host, device, usage, cuda_dir):

  '''
  deepmd_parallel: run deepmd calculation in parallel.

  Args:
    work_dir: string
      work_dir is the working directory of CP2K_kit.
    iter_id: int
      iter_id is the iteration id.
    use_prev_model: bool
      use_prev_model is whether we need to use previous model.
    start: int
      start is the starting model id.
    end: int
      end is the endding model id.
    parallel_exe: string
      parallel_exe is the parallel exacutable file.
    host: 1-d string list
      host is the name of computational nodes.
    device: 2-d string list
      device is the GPU device.
    usage: 2-d float list
      usage is the memory use of GPU.
    cuda_dir: string
      cuda_dir is the directory of cuda.
  Returns:
    none
  '''

  #run lammps in 1 thread. Here we just run force, it is a single
  #point calculation.

  model_num = end-start+1

  deepmd_train_dir = ''.join((work_dir, '/iter_', str(iter_id), '/01.train'))
  model_ckpt_file_exists = []
  lcurve_file_exists = []
  final_batch = []
  for i in range(model_num):
    if ( i == 0 ):
      input_file = ''.join((deepmd_train_dir, '/', str(i), '/input.json'))
      with open(input_file, 'r') as f:
        deepmd_dic = json.load(f)
      save_freq = deepmd_dic['training']['save_freq']
    model_ckpt_file = ''.join((deepmd_train_dir, '/', str(i), '/model.ckpt.index'))
    lcurve_file = ''.join((deepmd_train_dir, '/', str(i), '/lcurve.out'))
    model_ckpt_file_exists.append(os.path.exists(model_ckpt_file))
    lcurve_file_exists.append(os.path.exists(lcurve_file))
    if ( os.path.exists(lcurve_file) ):
      whole_line_num = len(open(lcurve_file, 'r').readlines())
      line = linecache.getline(lcurve_file, whole_line_num)
      linecache.clearcache()
      line_split = data_op.split_str(line, ' ', '\n')
      if ( len(line_split) > 0 and data_op.eval_str(line_split[0]) == 1 ):
        final_batch.append(int(line_split[0]))
      else:
        final_batch.append(0)
    else:
      final_batch.append(0)

  if ( all(file_exist for file_exist in model_ckpt_file_exists) and \
       all(file_exist for file_exist in lcurve_file_exists) and \
       all(i > save_freq for i in final_batch) ):
    dp_cmd = 'dp train --restart model.ckpt input.json 1>> log.out 2>> log.err'
  else:
    if ( use_prev_model and iter_id>0 ):
      for i in range(model_num):
        model_dir = ''.join((deepmd_train_dir, '/', str(i)))
        prev_model_dir = ''.join((work_dir, '/iter_', str(iter_id-1), '/01.train/', str(i)))
        cmd = "cp %s %s" %('model.ckpt.*', model_dir)
        call.call_simple_shell(prev_model_dir, cmd)
      dp_cmd = 'dp train --init-model model.ckpt input.json 1> log.out 2> log.err'
    else:
      dp_cmd = 'dp train input.json 1> log.out 2> log.err'

  if ( len(host) == 1 and len(device[0]) == 0 ):
    run = '''
#! /bin/bash

direc=%s
parallel_num=%d
run_start=%d
run_end=%d
parallel_exe=%s

seq $run_start $run_end | $parallel_exe -j $parallel_num $direc/produce.sh {} $direc
''' %(deepmd_train_dir, model_num, start, end, parallel_exe)

    produce = '''
#! /bin/bash

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

dp_path=%s

export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

x=$1
direc=$2
cd $direc/$x
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd %s
''' %(dp_path, dp_cmd, work_dir)

    run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
    with open(run_file_name_abs, 'w') as f:
      f.write(run)

    produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
    with open(produce_file_name_abs, 'w') as f:
      f.write(produce)

    subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
    subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
    try:
      subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
    except subprocess.CalledProcessError as err:
      log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

  #Case 2
  if ( len(host) > 1 and all(len(i) == 0 for i in device) ):
    host_list = []
    for i in range(len(host)):
      host_list.append('-S' + ' ' + host[i])
    if ( len(host) < model_num ):
      host_list = host_list*math.ceil(model_num/len(host))
    host_list = host_list[0:model_num]
    host_comb = data_op.comb_list_2_str(host_list, ' ')

    run = '''
#! /bin/bash

direc=%s
parallel_num=%d
run_start=%d
run_end=%d
parallel_exe=%s

seq $run_start $run_end | $parallel_exe -j $parallel_num %s $direc/produce.sh {} $direc
''' %(deepmd_train_dir, math.ceil(model_num/len(host)), start, end, parallel_exe, host_comb)

    produce = '''
#! /bin/bash

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

dp_path=%s

export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

x=$1
direc=$2
cd $direc/$x
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd %s
''' %(dp_path, dp_cmd, work_dir)

    run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
    with open(run_file_name_abs, 'w') as f:
      f.write(run)

    produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
    with open(produce_file_name_abs, 'w') as f:
      f.write(produce)

    subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
    subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
    try:
      subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
    except subprocess.CalledProcessError as err:
      log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

  #Case 3
  #If there is just 1 gpu device in the node, we prefer to run deepmd in serial.
  if ( len(host) == 1 and len(device[0]) == 1 ):
    run = '''
#! /bin/bash

dp_path=%s

export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

CUDA_DIR=%s
export PATH=$CUDA_DIR/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_DIR/lib64:$LD_LIBRARY_PATH

export KMP_BLOCKTIME=0
export KMP_AFFINITY=granularity=fine,verbose,compact,1,0

%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
''' %(dp_path, cuda_dir, dp_cmd)
    for i in range(model_num):
      deepmd_train_i_dir = ''.join((deepmd_train_dir, '/', str(i)))
      run_file_name_abs = ''.join((deepmd_train_i_dir, '/run.sh'))
      with open(run_file_name_abs, 'w') as f:
        f.write(run)
      subprocess.run('chmod +x run.sh', cwd=deepmd_train_i_dir, shell=True)
      try:
        subprocess.run("bash -c './run.sh'", cwd=deepmd_train_i_dir, shell=True)
      except subprocess.CalledProcessError as err:
        log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_i_dir))

  #Case 4
  if ( len(host) == 1 and len(device[0]) > 1 ):
    if ( len(device[0]) >= model_num ):
      device_choose = device[0][0:model_num]
      device_str = data_op.comb_list_2_str(device_choose, ' ')
      model_list = data_op.gen_list(start, end, 1)
      model_str = data_op.comb_list_2_str(model_list, ' ')

      run = '''
#! /bin/bash

model="%s"
device="%s"
direc=%s
parallel_num=%d
parallel_exe=%s

model_arr=(${model///})
device_arr=(${device///})

num=${#model_arr[*]}

for ((i=0;i<=num-1;i++));
do
model_device_arr[i]="${model_arr[i]} ${device_arr[i]}"
done

for i in "${model_device_arr[@]}"; do echo "$i"; done | $parallel_exe -j $parallel_num $direc/produce.sh {} $direc
''' %(model_str, device_str, deepmd_train_dir, model_num, parallel_exe)

      produce = '''
#! /bin/bash

dp_path=%s
export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

CUDA_DIR=%s
export PATH=$CUDA_DIR/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_DIR/lib64:$LD_LIBRARY_PATH

export KMP_BLOCKTIME=0
export KMP_AFFINITY=granularity=fine,verbose,compact,1,0

x=$1
direc=$2

x_arr=(${x///})

export CUDA_VISIBLE_DEVICES=${x_arr[1]}

cd $direc/${x_arr[0]}
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd $s
''' %(dp_path, cuda_dir, dp_cmd, work_dir)

      run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
      with open(run_file_name_abs, 'w') as f:
        f.write(run)

      produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
      with open(produce_file_name_abs, 'w') as f:
        f.write(produce)

      subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
      subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
      try:
        subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
      except subprocess.CalledProcessError as err:
        log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

    else:
      run_start = 0
      run_end = run_start+len(device[0])-1
      cycle = math.ceil(model_num/len(device[0]))
      for i in range(cycle):
        device_str = data_op.comb_list_2_str(device[0][0:(run_end-run_start+1)], ' ')
        model_list = data_op.gen_list(run_start, run_end, 1)
        model_str = data_op.comb_list_2_str(model_list, ' ')
        run = '''
#! /bin/bash

model="%s"
device="%s"
direc=%s
parallel_num=%d
parallel_exe=%s

model_arr=(${model///})
device_arr=(${device///})

num=${#model_arr[*]}

for ((i=0;i<=num-1;i++));
do
model_device_arr[i]="${model_arr[i]} ${device_arr[i]}"
done

for i in "${model_device_arr[@]}"; do echo "$i"; done | $parallel_exe -j $parallel_num $direc/produce.sh {} $direc
''' %(model_str, device_str, deepmd_train_dir, run_end-run_start+1, parallel_exe)

        produce = '''
#! /bin/bash

dp_path=%s
export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

CUDA_DIR=%s
export PATH=$CUDA_DIR/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_DIR/lib64:$LD_LIBRARY_PATH

export KMP_BLOCKTIME=0
export KMP_AFFINITY=granularity=fine,verbose,compact,1,0

x=$1
direc=$2

x_arr=(${x///})

export CUDA_VISIBLE_DEVICES=${x_arr[1]}

cd $direc/${x_arr[0]}
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd %s
''' %(dp_path, cuda_dir, dp_cmd, work_dir)

        run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
        with open(run_file_name_abs, 'w') as f:
          f.write(run)

        produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
        with open(produce_file_name_abs, 'w') as f:
          f.write(produce)

        subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
        subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
        try:
          subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
        except subprocess.CalledProcessError as err:
          log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

        run_start = run_start + len(device[0])
        run_end = run_end + len(device[0])
        if ( run_end > end):
          run_end = end

  #Case 5
  if ( len(host) > 1 and not all(len(i) == 0 for i in device) and len(data_op.list_replicate(device)) == 1 ):

    host_exp = []
    for i in range(len(host)):
      for j in range(len(device[i])):
        host_exp.append(host[i])
    device_exp = data_op.list_reshape(device)

    if ( len(device_exp) >= model_num ):
      host_list = []
      for i in range(len(model_num)):
        host_list.append('-S' + ' ' + host_exp[i])
      host_list = host_list[0:model_num]
      host_comb = data_op.comb_list_2_str(host_list, ' ')
      device_choose = device_exp[0:model_num]
      device_str = data_op.comb_list_2_str(device_choose, ' ')
      model_list = data_op.gen_list(start, end, 1)
      model_str = data_op.comb_list_2_str(model_list, ' ')

      run = '''
#! /bin/bash

model="%s"
device="%s"
direc=%s
parallel_num=%d
parallel_exe=%s

model_arr=(${model///})
device_arr=(${device///})

num=${#model_arr[*]}

for ((i=0;i<=num-1;i++));
do
model_device_arr[i]="${model_arr[i]} ${device_arr[i]}"
done

for i in "${model_device_arr[@]}"; do echo "$i"; done | $parallel_exe -j $parallel_num %s $direc/produce.sh {} $direc
''' %(model_str, device_str, deepmd_train_dir, model_num, parallel_exe, host_comb)

      produce = '''
#! /bin/bash

dp_path=%s
export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

CUDA_DIR=%s
export PATH=$CUDA_DIR/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_DIR/lib64:$LD_LIBRARY_PATH

export KMP_BLOCKTIME=0
export KMP_AFFINITY=granularity=fine,verbose,compact,1,0

x=$1
direc=$2

export CUDA_VISIBLE_DEVICES=${x_arr[1]}

cd $direc/${x_arr[0]}
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd %s
''' %(dp_path, cuda_dir, dp_cmd, work_dir)

      run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
      with open(run_file_name_abs, 'w') as f:
        f.write(run)

      produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
      with open(produce_file_name_abs, 'w') as f:
        f.write(produce)

      subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
      subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
      try:
        subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
      except subprocess.CalledProcessError as err:
        log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

    else:
      run_start = 0
      run_end = run_start+len(device_exp)-1
      cycle = math.ceil(model_num/len(device_exp))
      for i in range(cycle):
        device_str = data_op.comb_list_2_str(device_exp[0:(run_end-run_start+1)], ' ')
        model_list = data_op.gen_list(run_start, run_end, 1)
        model_str = data_op.comb_list_2_str(model_list, ' ')
        host_list = []
        for j in range(run_end-run_start+1):
          host_list.append('-S' + ' ' + host_exp[j])
        host_comb = data_op.comb_list_2_str(host_list, ' ')

        run = '''
#! /bin/bash

model="%s"
device="%s"
direc=%s
parallel_num=%d
parallel_exe=%s

model_arr=(${model///})
device_arr=(${device///})

num=${#model_arr[*]}

for ((i=0;i<=num-1;i++));
do
model_device_arr[i]="${model_arr[i]} ${device_arr[i]}"
done

for i in "${model_device_arr[@]}"; do echo "$i"; done | $parallel_exe -j $parallel_num %s $direc/produce.sh {} $direc
''' %(model_str, device_str, deepmd_train_dir, run_end-run_start+1, parallel_exe, host_comb)

        produce = '''
#! /bin/bash

dp_path=%s
export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

CUDA_DIR=%s
export PATH=$CUDA_DIR/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_DIR/lib64:$LD_LIBRARY_PATH

export KMP_BLOCKTIME=0
export KMP_AFFINITY=granularity=fine,verbose,compact,1,0

x=$1
direc=$2

x_arr=(${x///})

export CUDA_VISIBLE_DEVICES=${x_arr[1]}

cd $direc/${x_arr[0]}
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd %s
''' %(dp_path, cuda_dir, dp_cmd, work_dir)

        run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
        with open(run_file_name_abs, 'w') as f:
          f.write(run)

        produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
        with open(produce_file_name_abs, 'w') as f:
          f.write(produce)

        subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
        subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
        try:
          subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
        except subprocess.CalledProcessError as err:
          log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

        run_start = run_start + len(device[0])
        run_end = run_end + len(device[0])
        if ( run_end > end):
          run_end = end

  #Case 6
  if ( len(host) > 1 and not all(len(i) == 0 for i in device) and len(data_op.list_replicate(device)) != 1 ):
    host_true = []
    for i in range(len(host)):
      if ( len(device[i]) != 0 ):
        host_true.append(host[i])
    if ( len(host_true) >= model_num ):
      host_list = []
      for i in range(model_num):
        host_list.append('-S' + ' ' + host_true[j])
      host_comb = data_op.comb_list_2_str(host_list, ' ')

      run = '''
#! /bin/bash

direc=%s
parallel_num=%d
run_start=%d
run_end=%d
parallel_exe=%s

seq $run_start $run_end | $parallel_exe -j $parallel_num %s $direc/produce.sh {} $direc
''' %(deepmd_train_dir, model_num, start, end, parallel_exe, host_comb)

      produce = '''
#! /bin/bash

CUDA_DIR=%s
export PATH=$CUDA_DIR/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_DIR/lib64:$LD_LIBRARY_PATH

dp_path=%s
export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

x=$1
direc=$2
cd $direc/$x
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd %s
''' %(cuda_dir, dp_path, dp_cmd, work_dir)

      run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
      with open(run_file_name_abs, 'w') as f:
        f.write(run)

      produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
      with open(produce_file_name_abs, 'w') as f:
        f.write(produce)

      subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
      subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
      try:
        subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
      except subprocess.CalledProcessError as err:
        log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

    else:
      run_start = 0
      run_end = run_start+len(host_true)-1
      cycle = math.ceil(model_num/len(host_true))
      for i in range(cycle):
        host_list = []
        for j in range(run_end-run_start+1):
          host_list.append('-S' + ' ' + host_true[j])
        host_comb = data_op.comb_list_2_str(host_list, ' ')
        run = '''
#! /bin/bash

direc=%s
parallel_num=%d
run_start=%d
run_end=%d
parallel_exe=%s

seq $run_start $run_end | $parallel_exe -j $parallel_num %s $direc/produce.sh {} $direc
''' %(deepmd_train_dir, run_end-run_start+1, run_start, run_end, parallel_exe, host_comb)

        produce = '''
#! /bin/bash

CUDA_DIR=%s
export PATH=$CUDA_DIR/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_DIR/lib64:$LD_LIBRARY_PATH

dp_path=%s
export PATH=$dp_path/bin:$PATH
export LD_LIBRARY_PATH=$dp_path/lib:$LD_LIBRARY_PATH

x=$1
direc=$2
cd $direc/$x
%s
dp freeze -o frozen_model.pb 1>> log.err 2>> log.err
cd %s
''' %(cuda_dir, dp_path, dp_cmd, work_dir)

        run_file_name_abs = ''.join((deepmd_train_dir, '/run.sh'))
        with open(run_file_name_abs, 'w') as f:
          f.write(run)

        produce_file_name_abs = ''.join((deepmd_train_dir, '/produce.sh'))
        with open(produce_file_name_abs, 'w') as f:
          f.write(produce)

        subprocess.run('chmod +x run.sh', cwd=deepmd_train_dir, shell=True)
        subprocess.run('chmod +x produce.sh', cwd=deepmd_train_dir, shell=True)
        try:
          subprocess.run("bash -c './run.sh'", cwd=deepmd_train_dir, shell=True)
        except subprocess.CalledProcessError as err:
          log_info.log_error('Running error: %s command running error in %s' %(err.cmd, deepmd_train_dir))

        run_start = run_start + len(host_true)
        run_end = run_end + len(host_true)
        if ( run_end > end ):
          run_end = end

def run_deepmd(work_dir, iter_id, use_prev_model, parallel_exe, dp_path, host, device, usage, cuda_dir):

  '''
  run_deepmd: kernel function to run deepmd.

  Args:
    work_dir: string
      work_dir is working directory of CP2K_kit.
    iter_id: int
      iter_id is the iteration id.
    use_prev_model: bool
      use_prev_model is whether we need to use previous model.
    parallel_exe: string
      parallel_exe is the parallel exacutable file.
    host: 1-d string list
      host is the name of computational nodes.
    device: 2-d string list
      device is the GPU device.
    usage: 2-d float list
      usage is the memory use of GPU.
    cuda_dir: string
      cuda_dir is the directory of cuda.
  Returns:
    none
  '''

  import subprocess

  train_dir = ''.join((work_dir, '/iter_', str(iter_id), '/01.train'))
  model_num = len(call.call_returns_shell(train_dir, "ls -ll |awk '/^d/ {print $NF}'"))

  #Check generating deepmd tasks
  check_deepmd_gen = []
  for i in range(model_num):
    inp_file_name_abs = ''.join((train_dir, '/', str(i), '/input.json'))
    if ( os.path.exists(inp_file_name_abs) and os.path.getsize(inp_file_name_abs) != 0 ):
      check_deepmd_gen.append(0)
    else:
      check_deepmd_gen.append(1)

  if ( len(check_deepmd_gen) != 0 and all(i == 0 for i in check_deepmd_gen) ):
    str_print = 'Success: generate deepmd-kit tasks in %s' %(train_dir)
    str_print = data_op.str_wrap(str_print, 80, '  ')
    print (str_print, flush=True)
  else:
    log_info.log_error('Generating deepmd-kit tasks error, please check iteration %d' %(iter_id))
    exit()

  if ( not all(len(i) == 0 for i in device) and cuda_dir == 'none' ):
    log_info.log_error('Input error: there are gpu devices in nodes, but cuda_dir is none, please set cuda directory in deepff/environ/cuda_dir')
    exit()
  #Run deepmd-kit tasks
  deepmd_parallel(work_dir, iter_id, use_prev_model, 0, model_num-1, parallel_exe, dp_path, host, device, usage, cuda_dir)

  #Check the deepmd tasks.
  check_deepmd_run = []
  for i in range(model_num):
    ff_file_name_abs = ''.join((train_dir, '/', str(i), '/frozen_model.pb'))
    if ( os.path.exists(ff_file_name_abs) and os.path.getsize(ff_file_name_abs) ):
      check_deepmd_run.append(0)
    else:
      check_deepmd_run.append(1)

  if ( len(check_deepmd_run) != 0 and all(i == 0 for i in check_deepmd_run) ):
    print ('  Success: train %d models by deepmd-kit' %(model_num), flush=True)
  else:
    log_info.log_error('deepmd-kit running error, please check iteration %d' %(iter_id))
    exit()

if __name__ == '__main__':
  from CP2K_kit.deepff import deepmd_run
  from CP2K_kit.tools import read_input
  from CP2K_kit.deepff import load_data
  from CP2K_kit.deepff import check_deepff

  deepff_key = ['deepmd', 'lammps', 'cp2k', 'model_devi', 'environ']
  work_dir = '/home/lujunbo/code/github/CP2K_kit/deepff/work_dir'

  deepmd_dic, lammps_dic, cp2k_dic, model_devi_dic, environ_dic = \
  read_input.dump_info(work_dir, 'input.inp', deepff_key)
  proc_num = 4
  deepmd_dic, lammps_dic, cp2k_dic, model_devi_dic, environ_dic = \
  check_deepff.check_inp(deepmd_dic, lammps_dic, cp2k_dic, model_devi_dic, environ_dic, proc_num)

  seed = [1,2,3,4]
  numb_test = int(deepmd_dic['training']['numb_test'])

  i = 0
  init_train_data = []
  cmd = "mkdir %s" % ('init_train_data')
  call.call_simple_shell(work_dir, cmd)
  train_dic = deepmd_dic['training']
  for key in train_dic:
    if ( 'system' in key):
      init_train_key_dir = train_dic[key]['directory']
      proj_name = train_dic[key]['proj_name']
      save_dir = ''.join((work_dir, '/init_train_data/data_', str(i)))
      init_train_data.append(save_dir)
      load_data.load_data_from_dir(init_train_key_dir, work_dir, save_dir, proj_name)
      load_data.raw_to_set(save_dir, 1)
      i = i+1

  #Test gen_deepmd_task function
  deepmd_run.gen_deepmd_task(deepmd_dic, work_dir, 0, init_train_data, seed, numb_test)
  #Test run_deepmd function
  deepmd_run.run_deepmd(work_dir, 0)
