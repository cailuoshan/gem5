# All rights reserved.
#
# The license below extends only to copyright in the software and shall
# not be construed as granting a license to any other intellectual
# property including but not limited to intellectual property relating
# to a hardware implementation of the functionality of the software
# licensed hereunder.  You may use the software subject to the license
# terms below provided that you ensure that this notice is replicated
# unmodified and in its entirety in all distributions of the software,
# modified or unmodified, in source code or in binary form.
#
# Copyright (c) 2021 Huawei International
# Copyright (c) 2012-2014 Mark D. Hill and David A. Wood
# Copyright (c) 2009-2011 Advanced Micro Devices, Inc.
# Copyright (c) 2006-2007 The Regents of The University of Michigan
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import argparse
import sys
from os import path

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.util import (
    addToPath,
    fatal,
    warn,
)
from m5.util.fdthelper import *

from gem5.utils.requires import requires

addToPath("../")

from common import (
    CacheConfig,
    CpuConfig,
    MemConfig,
    ObjectList,
    Options,
    Simulation,
)
from common.Benchmarks import *
from common.Caches import *
from common.FSConfig import *
from common.SysPaths import *
from ruby import Ruby


# Usage: ./build/RISCV/gem5.opt configs/example/riscv_fs_cpt.py \
# --cpu-type=DerivO3CPU --caches --mem-type=DDR3_1600_8x8 --mem-size=8GB \
# --raw-cpt --generic-rv-cpt=$raw_cpt

# ./build/RISCV/gem5.opt configs/example/riscv_fs_cpt.py \
# --cpu-type=DerivO3CPU --caches --mem-type=DDR3_1600_8x8 --mem-size=8GB \
# --generic-rv-cpt=$checkpoint --restore-rvv-cpt \
# --vlen=128 --elen=64
        

# ------------------------- Usage Instructions ------------------------- #
# Common system confirguration options (cpu types, num cpus, checkpointing
# etc.) should be supported
#
# Ruby not supported in this config file. Not tested on RISC-V FS Linux (as
# of 25 March 2021).
#
# Options (Full System):
# --kernel (required):          Bootloader + kernel binary (e.g. bbl with
#                               linux kernel payload)
# --disk-image (optional):      Path to disk image file. Not needed if using
#                               ramfs (might run into issues though).
# --virtio-rng (optional):      Enable VirtIO entropy source device
# --command-line (optional):    Specify to override default.
# --dtb-filename (optional):    Path to DTB file. Auto-generated if empty.
# --bare-metal (boolean):       Use baremetal Riscv (default False). Use this
#                               if bbl is built with "--with-dts" option.
#                               (do not forget to include bootargs in dts file)
#
# Not Used:
# --command-line-file, --script, --frame-capture, --os-type, --timesync,
# --dual, -b, --etherdump, --root-device, --ruby


def build_test_system(np, args):
    (CPUClass, _) = Simulation.getCPUClass(args.cpu_type)

    # -------------------- make BareMetal Riscv System -------------------- #
    system = System()
    mdesc = SysConfig(mem=args.mem_size)
    system.mem_mode = 'timing'
    system.mem_ranges = [AddrRange(start=0x80000000, size=mdesc.mem())]
    print(system.mem_ranges)

    system.workload = RiscvBareMetal()
    system.workload.reset_vect = 0x80000000

    system.iobus = IOXBar()
    system.membus = MemBus()
    system.bridge = Bridge(delay='50ns')
    system.bridge.mem_side_port = system.iobus.cpu_side_ports
    system.bridge.cpu_side_port = system.membus.mem_side_ports
    
    system.uartlite  = UartLite()
    system.uartlite.pio = system.iobus.mem_side_ports

    system.lint = Clint()
    system.lint.pio = system.iobus.mem_side_ports
    system.lint.pio_addr = 0x38000000
    system.lint.num_threads = np

    system.plic = NemuPlic()
    system.plic.pio = system.iobus.mem_side_ports

    system.bridge.ranges = [
        AddrRange(system.uartlite.pio_addr, system.uartlite.pio_addr +
        system.uartlite.pio_size),
        AddrRange(system.lint.pio_addr, system.lint.pio_addr + system.lint.pio_size),
        AddrRange(system.plic.pio_addr, system.plic.pio_addr + system.plic.pio_size),
    ]

    system.system_port = system.membus.cpu_side_ports
    system.xiangshan_system = True

    # ---------------------------- Default Setup --------------------------- #
    # Set the cache line size for the entire system
    system.cache_line_size = args.cacheline_size

    # Create a top-level voltage domain
    system.voltage_domain = VoltageDomain(voltage=args.sys_voltage)

    # Create a source clock for the system and set the clock period
    system.clk_domain = SrcClockDomain(
        clock=args.sys_clock, voltage_domain=system.voltage_domain
    )

    # Create a CPU voltage domain
    system.cpu_voltage_domain = VoltageDomain()

    # Create a source clock for the CPUs and set the clock period
    system.cpu_clk_domain = SrcClockDomain(
        clock=args.cpu_clock, voltage_domain=system.cpu_voltage_domain
    )

    # For now, assign all the CPUs to the same clock domain
    print(type(CPUClass))
    system.cpu = [
        CPUClass(clk_domain=system.cpu_clk_domain, cpu_id=i) for i in range(np)
    ]
    # PMA Checker
    for cpu in system.cpu:
        cpu.mmu.pma_checker = PMAChecker(
            uncacheable=[AddrRange(0, size=0x80000000)])

    if args.caches or args.l2cache:
        # By default the IOCache runs at the system clock
        system.iocache = IOCache(addr_ranges=system.mem_ranges)
        system.iocache.cpu_side = system.iobus.mem_side_ports
        system.iocache.mem_side = system.membus.cpu_side_ports
    elif not args.external_memory_system:
        system.iobridge = Bridge(delay="50ns", ranges=system.mem_ranges)
        system.iobridge.cpu_side_port = system.iobus.mem_side_ports
        system.iobridge.mem_side_port = system.membus.cpu_side_ports

    for i in range(np):
        if not ObjectList.is_kvm_cpu(CPUClass):
            if args.bp_type:
                bpClass = ObjectList.bp_list.get(args.bp_type)
                system.cpu[i].branchPred = bpClass()
            if args.indirect_bp_type:
                IndirectBPClass = ObjectList.indirect_bp_list.get(
                    args.indirect_bp_type
                )
                system.cpu[i].branchPred.indirectBranchPred = IndirectBPClass()
        system.cpu[i].createThreads()
        print("Create threads for test sys cpu ({})".format(type(system.cpu[i])))
        system.cpu[i].isa[0].elen = args.elen
        system.cpu[i].isa[0].vlen = args.vlen    

    CacheConfig.config_cache(args, system)

    MemConfig.config_mem(args, system)

    # config gcpt_restorer
    if args.gcpt_restorer is None:
        if args.raw_cpt:
            # If using raw binary, no restorer is needed.
            gcpt_restorer = None
        elif args.num_cpus > 1:
            if "GCB_MULTI_CORE_RESTORER" in os.environ:
                gcpt_restorer = os.environ["GCB_MULTI_CORE_RESTORER"]
                print("Obtained gcpt_restorer from GCB_MULTI_CORE_RESTORER: ", gcpt_restorer)
            else:
                fatal("Plz set $GCB_MULTI_CORE_RESTORER when model Xiangshan with multi-core")
        elif args.restore_rvv_cpt:
            if "GCBV_RESTORER" in os.environ:
                gcpt_restorer = os.environ["GCBV_RESTORER"]
                print("Obtained gcpt_restorer from GCBV_RESTORER: ", gcpt_restorer)
            else:
                gcpt_restorer = ""
        # elif args.restore_rvh_cpt:
        #     if "GCBH_RESTORER" in os.environ:
        #         gcpt_restorer = os.environ["GCBH_RESTORER"]
        #         print("Obtained gcpt_restorer from GCBH_RESTORER: ", gcpt_restorer)
        #     else:
        #         fatal("Plz set $GCBH_RESTORER when running RVH checkpoints")
        else:
            if "GCB_RESTORER" in os.environ:
                gcpt_restorer = os.environ["GCB_RESTORER"]
                print("Obtained gcpt_restorer from GCB_RESTORER: ", gcpt_restorer)
            else:
                gcpt_restorer = ""
    else:
        print("Obtained gcpt_restorer from args.gcpt_restorer: ", args.gcpt_restorer)
        gcpt_restorer = args.gcpt_restorer

    if args.num_cpus > 1:
        print("Simulating a multi-core system, demanding a larger GCPT restorer size (2M).")
        system.gcpt_restorer_size_limit = 2**20
    elif args.restore_rvv_cpt:
        print("Simulating single core with RVV, demanding GCPT restorer size of 0x1000.")
        system.gcpt_restorer_size_limit = 0x1000
    # elif args.restore_rvh_cpt:
    #     print("Simulating single core with RVH, demanding GCPT restorer size of 0x1000.")
    #     system.gcpt_restorer_size_limit = 0x1000
    else:
        print("Simulating single core without RVV, demanding GCPT restorer size of 0x700.")
        system.gcpt_restorer_size_limit = 0x700

    # configure gcpt input
    if args.generic_rv_cpt is not None:
        # assert(buildEnv['TARGET_ISA'] == "riscv")
        system.restore_from_gcpt = True
        system.gcpt_file = args.generic_rv_cpt

        system.workload.bootloader = ''
        system.workload.xiangshan_cpt = True

        if args.raw_cpt:
            assert not args.gcpt_restorer  # raw_cpt and gcpt_restorer are exclusive
            print('Using raw bbl', args.generic_rv_cpt)
            system.map_to_raw_cpt = True
            system.workload.raw_bootloader = True
        else:
            system.gcpt_restorer_file = gcpt_restorer

    # configure DRAMSim input
    if args.mem_type == 'DRAMsim3' and args.dramsim3_ini is None:
        # use relative path to find the dramsim3 ini file, from configs/common/ to root
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        args.dramsim3_ini = os.path.join(root_dir, 'ext/dramsim3/xiangshan_configs/xiangshan_DDR4_8Gb_x8_3200_2ch.ini')

    return system

if __name__ == '__m5_main__':
    # Run a check to ensure the RISC-V ISA is complied into gem5.
    requires(isa_required=ISA.RISCV)

    # Add args
    parser = argparse.ArgumentParser()
    Options.addCommonOptions(parser, ISA.RISCV)
    Options.addXiangshanFSOptions(parser)
    args = parser.parse_args()

    FutureClass = None
    # Match the memories with the CPUs, based on the options for the test system
    MemClass = Simulation.setMemClass(args)

    system = build_test_system(args.num_cpus, args)

    root = Root(full_system=True, system=system)

    Simulation.run_vanilla(args, root, system, FutureClass)
