#!/usr/bin/env python

# This workflow generates full MC events from generator through CAF stage

import sys, os
import json
import pathlib
import functools
from typing import Dict, List

from sbn_parsl.workflow import StageType, Stage, Workflow, WorkflowExecutor, \
        DefaultStageTypes
from sbn_parsl.templates import CMD_TEMPLATE_CONTAINER
from sbn_parsl.components import larsoft_runfunc, build_larsoft_cmd
from sbn_parsl.app import entry_point
from sbn_parsl.metadata import MetadataGenerator


def build_modify_fcl_cmd(context):
    """generate bash commands that modify fcl"""
    fcl_cmd = ''
    fcl_name = os.path.basename(context.fcl)
    if context.stage.stage_type == DefaultStageTypes.GEN:
        run_number = 1 + (context.stage.workflow_id // 100)
        subrun_number = context.stage.workflow_id % 100
        fcl_cmd = '\n'.join([
            f'echo "source.firstRun: {run_number}" >> {fcl_name}',
            f'echo "source.firstSubRun: {subrun_number}" >> {fcl_name}',
            f'''echo "physics.producers.generator.FluxSearchPaths: \\"/lus/flare/projects/dune_hpc/Inputs/FluxFiles/atmos/Honda_interp\\"" >> {fcl_name}''',
        ])
    elif context.stage.stage_type == DefaultStageTypes.RECO2:
        fcl_cmd = '\n'.join([
            r'export FW_SEARCH_DIR=/lus/flare/projects/dune_hpc/Inputs:$FW_SEARCH_DIR',
            f'''echo "physics.producers.cvneva.TFNetHandler.TFProtoBuf: \\"/lus/flare/projects/dune_hpc/Inputs/CVN/atmos/v05_00_00/dune_cvn_beamarch_hd_2x6_atmospherics_tf26.pb\\"" >> {fcl_name}''',
        ])

    return fcl_cmd

def build_larsoft_cmd_rename_caf(context) -> str:
    lar_cmd = build_larsoft_cmd(context)
    if context.stage.stage_type != DefaultStageTypes.CAF:
        return lar_cmd

    # rename caf file
    input_stem = pathlib.Path(context.input_files[0]).stem
    return '&&'.join([
        lar_cmd,
        f'mv caf.root {input_stem}.caf.root',
        f'mv flatcaf.root {input_stem}.flat.caf.root'
    ])

mc_runfunc_dune=functools.partial(larsoft_runfunc, \
    fcl_cmd_func=build_modify_fcl_cmd, \
    lar_cmd_func=build_larsoft_cmd_rename_caf)


class Reco2FromGenExecutor(WorkflowExecutor):
    """Execute a Gen -> G4 -> Detsim -> Reco1 -> Reco2 workflow from user settings."""
    def __init__(self, settings: json):
        super().__init__(settings)
        self.meta = MetadataGenerator(settings['metadata'], self.fcls, defer_check=True)
        self.stage_order = [DefaultStageTypes.from_str(key) for key in self.fcls.keys()]
        self.subruns_per_caf = settings['workflow']['subruns_per_caf']
        self.runfunc = functools.partial(mc_runfunc_dune, executor=self, 
                                         template=CMD_TEMPLATE_CONTAINER,
                                         meta=None)

    def setup_single_workflow(self, iteration: int, file_slice=None, last_file=None):
        workflow = Workflow(self.stage_order, default_fcls=self.fcls)
        runfunc_ = self.runfunc
        s = Stage(DefaultStageTypes.CAF)
        s.runfunc = self.runfunc
        workflow.add_final_stage(s)
        s.run_dir = get_caf_dir(self.output_dir, iteration)

        for i in range(self.subruns_per_caf):
            inst = iteration * self.subruns_per_caf + i
            # create reco2 file from MC, only need to specify the last stage
            # since there are no inputs
            s2 = Stage(DefaultStageTypes.RECO2)
            s.add_parents(s2, workflow.default_fcls)

            # each reco2 file will have its own directory
            s2.run_dir = get_subrun_dir(self.output_dir, inst)

        return workflow


def get_subrun_dir(prefix: pathlib.Path, subrun: int):
    """Returns a path with directory structure like XXXX00/XXXXXX"""
    return prefix / f"{(subrun//1000):06d}" / f"{(subrun//100):06d}" / f"subrun_{subrun:06d}"

def get_caf_dir(prefix: pathlib.Path, subrun: int):
    """Returns a path with directory structure like XXXX00/caf/XXXXXX"""
    return prefix / f"{(subrun//1000):06d}" / 'caf' / f"subrun_{subrun:06d}"

if __name__ == '__main__':
    entry_point(sys.argv, Reco2FromGenExecutor)
