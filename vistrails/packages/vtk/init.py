###############################################################################
##
## Copyright (C) 2014-2015, New York University.
## Copyright (C) 2011-2014, NYU-Poly.
## Copyright (C) 2006-2011, University of Utah.
## All rights reserved.
## Contact: contact@vistrails.org
##
## This file is part of VisTrails.
##
## "Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
##
##  - Redistributions of source code must retain the above copyright notice,
##    this list of conditions and the following disclaimer.
##  - Redistributions in binary form must reproduce the above copyright
##    notice, this list of conditions and the following disclaimer in the
##    documentation and/or other materials provided with the distribution.
##  - Neither the name of the New York University nor the names of its
##    contributors may be used to endorse or promote products derived from
##    this software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
## THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
## PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
## CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
## EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
## PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
## OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
## WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
## OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
## ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."
##
###############################################################################
import re
import os.path

import vtk

from vistrails.core.modules.basic_modules import PathObject, \
                                                       identifier as basic_pkg
from vistrails.core.modules.config import ModuleSettings
from vistrails.core.modules.vistrails_module import ModuleError
from vistrails.core.modules.module_registry import get_module_registry
from vistrails.core.modules.output_modules import OutputModule, ImageFileMode, \
    ImageFileModeConfig
from vistrails.core.system import get_vistrails_default_pkg_prefix, systemType, current_dot_vistrails
from vistrails.core.upgradeworkflow import UpgradeWorkflowHandler,\
                                       UpgradeModuleRemap, UpgradePackageRemap
from vistrails.core.vistrail.connection import Connection
from vistrails.core.wrapper.pythonclass import BaseClassModule, gen_class_module

from .tf_widget import _modules as tf_modules
from .inspectors import _modules as inspector_modules
from .offscreen import _modules as offscreen_modules

from identifiers import identifier

from .vtk_wrapper import vtk_classes
from . import hasher


_modules = tf_modules + inspector_modules + offscreen_modules

registry = get_module_registry()
if registry.has_module('%s.spreadsheet' % get_vistrails_default_pkg_prefix(),
                       'SpreadsheetCell'):
    # load these only if spreadsheet is enabled
    from .vtkcell import _modules as cell_modules
    from .vtkviewcell import _modules as view_cell_modules
    from .vtkhandler import _modules as handler_modules
    _modules += cell_modules + view_cell_modules + handler_modules

class vtkRendererToFile(ImageFileMode):
    config_cls = ImageFileModeConfig
    formats = ['png', 'jpg', 'tif', 'pnm']

    @classmethod
    def can_compute(cls):
        return True

    def compute_output(self, output_module, configuration):
        format_map = {'png': vtk.vtkPNGWriter,
                      'jpg': vtk.vtkJPEGWriter,
                      'tif': vtk.vtkTIFFWriter,
                      'pnm': vtk.vtkPNMWriter}
        r = output_module.get_input("value").vtkInstance
        w = configuration["width"]
        h = configuration["height"]
        img_format = self.get_format(configuration)
        if img_format not in format_map:
            raise ModuleError(output_module,
                              'Cannot output in format "%s"' % img_format)
        fname = self.get_filename(configuration, suffix='.%s' % img_format)

        window = vtk.vtkRenderWindow()
        window.OffScreenRenderingOn()
        window.SetSize(w, h)

        # FIXME think this may be fixed in VTK6 so we don't have this
        # dependency...
        widget = None
        if systemType=='Darwin':
            from PyQt4 import QtCore, QtGui
            widget = QtGui.QWidget(None, QtCore.Qt.FramelessWindowHint)
            widget.resize(w, h)
            widget.show()
            window.SetWindowInfo(str(int(widget.winId())))

        window.AddRenderer(r)
        window.Render()
        win2image = vtk.vtkWindowToImageFilter()
        win2image.SetInput(window)
        win2image.Update()
        writer = format_map[img_format]()
        writer.SetInput(win2image.GetOutput())
        writer.SetFileName(fname)
        writer.Write()
        window.Finalize()
        if widget is not None:
            widget.close()

class vtkRendererOutput(OutputModule):
    # DAK: no render view here, use a separate module for this...
    _settings = ModuleSettings(configure_widget="vistrails.gui.modules."
                       "output_configuration:OutputModuleConfigurationWidget")
    _input_ports = [('value', 'vtkRenderer')]
    if registry.has_module('%s.spreadsheet' % get_vistrails_default_pkg_prefix(),
                       'SpreadsheetCell'):
        _input_ports.extend([('interactionHandler', 'vtkInteractionHandler'),
                             ('interactorStyle', 'vtkInteractorStyle'),
                             ('picker', 'vtkAbstractPicker')])
    _output_modes = [vtkRendererToFile]

_modules.append(vtkRendererOutput)

# TODO: code below is independent of VTK and should be moved elsewhere

####################################################################


# keep track of created modules for use as subclasses
klasses = {}

def initialize():
    # First check if spec for this VTK version exists
    v = vtk.vtkVersion()
    version = [v.GetVTKMajorVersion(),
               v.GetVTKMinorVersion(),
               v.GetVTKBuildVersion()]

    spec_name = os.path.join(current_dot_vistrails(), 'vtk-spec-%s.xml' % '_'.join([str(v) for v in version]))
    # TODO: how to patch with diff/merge
    if not os.path.exists(spec_name):
        from .vtk_wrapper.parse import parse
        parse(spec_name)
    vtk_classes.initialize(spec_name)
    _modules.insert(0, BaseClassModule)
    _modules.extend([gen_class_module(spec, vtk_classes, klasses, signature=hasher.vtk_hasher)
                     for spec in vtk_classes.specs.module_specs])

################# UPGRADES #####################################################

_remap = None
_controller = None
_pipeline = None

def _get_controller():
    global _controller
    return _controller

def _get_pipeline():
    global _pipeline
    return _pipeline

def build_remap(module_name=None):
    global _remap, _controller

    reg = get_module_registry()
    uscore_num = re.compile(r"(.+)_(\d+)$")

    def base_name(name):
        "returns name without overload index"
        i = name.find('_')
        if i != -1:
            return name[:i]
        return name
    def get_port_specs(descriptor, port_type):
        ports = {}
        for desc in reversed(reg.get_module_hierarchy(descriptor)):
            ports.update(reg.module_ports(port_type, desc))
        return ports

    def build_remap_method(desc, port_prefix, port_num, port_type):
        # for connection, need to differentiate between src and dst
        if port_type == 'input':
            conn_lookup = Connection._get_destination
            get_port_spec = reg.get_input_port_spec
            idx = 1
        else:
            conn_lookup = Connection._get_source
            get_port_spec = reg.get_output_port_spec
            idx = 0

        def remap(old_conn, new_module):
            create_new_connection = UpgradeWorkflowHandler.create_new_connection
            port = conn_lookup(old_conn)
            pipeline = _get_pipeline()
            modules = [pipeline.modules[old_conn.source.moduleId],
                       pipeline.modules[old_conn.destination.moduleId]]
            modules[idx] = new_module
            ports = [old_conn.source, old_conn.destination]
            for i in xrange(1, port_num):
                port_name = "%s_%d" % (port_prefix, i)
                port_spec = get_port_spec(modules[idx], port_name)
                if port_spec.sigstring == port.signature:
                    ports[idx] = port_name
                    new_conn = create_new_connection(_get_controller(),
                                                     modules[0],
                                                     ports[0],
                                                     modules[1],
                                                     ports[1])
                    return [('add', new_conn)]

            # if get here, just try to use _1 version?
            ports[idx] = "%s_%d" % (port_prefix, 1)
            new_conn = create_new_connection(_get_controller(),
                                             modules[0],
                                             ports[0],
                                             modules[1],
                                             ports[1])
            return [('add', new_conn)]
        return remap

    def build_function_remap_method(desc, port_prefix, port_num):
        f_map = {"vtkCellArray": {"InsertNextCell": 3}}
        def build_function(old_function, new_function_name, new_module):
            controller = _get_controller()
            if len(old_function.parameters) > 0:
                new_param_vals, aliases = \
                    zip(*[(p.strValue, p.alias)
                          for p in old_function.parameters])
            else:
                new_param_vals = []
                aliases = []
            new_function = controller.create_function(new_module,
                                                      new_function_name,
                                                      new_param_vals,
                                                      aliases)
            return new_function

        def remap(old_function, new_module):
            for i in xrange(1, port_num):
                port_name = "%s_%d" % (port_prefix, i)
                port_spec = reg.get_input_port_spec(new_module, port_name)
                old_sigstring = \
                    reg.expand_port_spec_string(old_function.sigstring,
                                                basic_pkg)
                if port_spec.sigstring == old_sigstring:
                    new_function = build_function(old_function, port_name,
                                                  new_module)
                    new_module.add_function(new_function)
                    return []
            port_idx = 1
            if desc.name in f_map:
                if port_prefix in f_map[desc.name]:
                    port_idx =  f_map[desc.name][port_prefix]
            port_name = "%s_%d" % (port_prefix, port_idx)
            new_function = build_function(old_function, port_name, new_module)
            new_module.add_function(new_function)
            return []

        return remap

    def process_ports(desc, remap, port_type):
        if port_type == 'input':
            remap_dict_key = 'dst_port_remap'
        else:
            remap_dict_key = 'src_port_remap'
        ports = get_port_specs(desc, port_type)
        port_nums = {}
        for port_name, port_spec in ports.iteritems():
            # FIXME just start at 1 and go until don't find port (no
            # need to track max)?
            search_res = uscore_num.search(port_name)
            if search_res:
                port_prefix = search_res.group(1)
                port_num = int(search_res.group(2))
                if port_prefix not in port_nums:
                    port_nums[port_prefix] = port_num
                elif port_num > port_nums[port_prefix]:
                    port_nums[port_prefix] = port_num
        for port_prefix, port_num in port_nums.iteritems():
            m = build_remap_method(desc, port_prefix, port_num, port_type)
            remap.add_remap(remap_dict_key, port_prefix, m)
            if port_type == 'input':
                m = build_function_remap_method(desc, port_prefix, port_num)
                remap.add_remap('function_remap', port_prefix, m)
        if port_type == 'output' and desc.name in klasses:
            remap.add_remap('src_port_remap', 'self', 'Instance')

    def process_module(desc):
        # 0.9.3 upgrades
        if not desc.name in klasses:
            return
        remap = UpgradeModuleRemap(None, '0.9.3', '0.9.3',
                                   module_name=desc.name)
        process_ports(desc, remap, 'input')
        process_ports(desc, remap, 'output')
        _remap.add_module_remap(remap)
        # 0.9.5 upgrades
        remap = UpgradeModuleRemap('0.9.3', '0.9.5', '0.9.5',
                                   module_name=desc.name)
        remap.add_remap('src_port_remap', 'self', 'Instance')
        _remap.add_module_remap(remap)
        # 1.0.0 upgrades
        input_mappings = {}
        function_mappings = {}
        for spec in [desc.module._get_input_spec(s)
                     for s in get_port_specs(desc, 'input')]:
            def change_func(name, value):
                def remap(old_func, new_module):
                    controller = _get_controller()
                    new_function = controller.create_function(new_module,
                                                              name,
                                                              [value])
                    return [('add', new_function, 'module', new_module.id)]
                return remap
            def change_SetXint(spec):
                # Fix old SetX methods that takes an int representing the enum
                def remap(old_func, new_module):
                    controller = _get_controller()
                    value = int(old_func.params[0].strValue)
                    value = spec.values[0][value]
                    new_function = controller.create_function(new_module,
                                                              spec.name,
                                                              [value])
                    return [('add', new_function, 'module', new_module.id)]
                return remap
            def color_func(name):
                def remap(old_func, new_module):
                    controller = _get_controller()
                    value = ','.join([p.strValue for p in old_func.params])
                    new_function = controller.create_function(new_module,
                                                              name,
                                                              [value])
                    return [('add', new_function, 'module', new_module.id)]
                return remap
            def file_func(name):
                def remap(old_func, new_module):
                    controller = _get_controller()
                    value = PathObject(old_func.params[0].strValue)
                    new_function = controller.create_function(new_module,
                                                              name,
                                                              [value])
                    return [('add', new_function, 'module', new_module.id)]
                return remap
            def to_file_func(name):
                # Add Path module as name->File converter
                def remap(old_conn, new_module):
                    controller = _get_controller()
                    create_new_connection = UpgradeWorkflowHandler.create_new_connection
                    pipeline = _get_pipeline()
                    module = pipeline.modules[old_conn.source.moduleId]
                    x = (module.location.x + new_module.location.x)/2
                    y = (module.location.y + new_module.location.y)/2
                    path_module = controller.create_module(basic_pkg, 'Path',
                                                           '', x, y)
                    conn1 = create_new_connection(controller,
                                                  module,
                                                  old_conn.source,
                                                  path_module,
                                                  'name')
                    conn2 = create_new_connection(controller,
                                                  path_module,
                                                  'value',
                                                  new_module,
                                                  name)
                    return [('add', path_module),
                            ('add', conn1),
                            ('add', conn2)]
                return remap
            if spec is None:
                continue
            elif spec.method_type == 'OnOff':
                # Convert On/Off to single port
                input_mappings[spec.name + 'On'] = spec.name
                input_mappings[spec.name + 'Off'] = spec.name
                function_mappings[spec.name + 'On'] = \
                                              change_func(spec.name, True)
                function_mappings[spec.name + 'Off'] = \
                                             change_func(spec.name, False)
            elif spec.method_type == 'nullary':
                # Add True to execute empty functions
                function_mappings[spec.name] = change_func(spec.name, True)
            elif spec.method_type == 'SetXToY':
                # Add one mapping for each default
                for enum in spec.values[0]:
                    input_mappings[spec.method_name + enum] = spec.name
                    # Add enum value to function
                    function_mappings[spec.method_name + enum] = \
                                                  change_func(spec.name, enum)
                # Convert SetX(int) methods
                old_name = spec.method_name[:-2]
                function_mappings[spec.method_name[:-2]] = change_SetXint(spec)
            elif spec.port_type == 'basic:Color':
                # Remove 'Widget' suffix on Color
                input_mappings[spec.method_name + 'Widget'] = spec.name
                # Remove 'Set prefix'
                input_mappings[spec.method_name] = spec.name
                # Change old type (float, float, float) -> (,)*3
                function_mappings[spec.method_name] = color_func(spec.name)
            elif spec.port_type == 'basic:File':
                input_mappings[spec.method_name] = to_file_func(spec.name)  # Set*FileName -> (->File->*File)
                input_mappings['Set' + spec.name] = spec.name # Set*File -> *File
                function_mappings[spec.method_name] = file_func(spec.name)
            elif spec.method_name == 'Set' + base_name(spec.name):
                # Remove 'Set' prefixes
                input_mappings['Set' + spec.name] = spec.name
            elif spec.name == 'AddInput_1':
                # FIXME what causes this?
                # New version does not have AddInput
                input_mappings['AddInput'] = 'AddInput_1'
        output_mappings = {}
        for spec_name in get_port_specs(desc, 'output'):
            spec = desc.module._get_output_spec(spec_name)
            if spec is None:
                continue
            if spec.method_name == 'Get' + spec.name:
                # Remove 'Get' prefixes
                output_mappings[spec.method_name] = spec.name

        remap = UpgradeModuleRemap('0.9.5', '1.0.0', '1.0.0',
                                   module_name=desc.name)
        for k, v in input_mappings.iteritems():
            remap.add_remap('dst_port_remap', k, v)
        for k, v in output_mappings.iteritems():
            remap.add_remap('src_port_remap', k, v)
        for k, v in function_mappings.iteritems():
            remap.add_remap('function_remap', k, v)
        _remap.add_module_remap(remap)

    pkg = reg.get_package_by_name(identifier)
    if module_name is not None:
        desc = reg.get_descriptor_by_name(identifier, module_name)
        process_module(desc)
    else:
        # FIXME do this by descriptor first, then build the hierarchies for each
        # module after that...
        for desc in pkg.descriptor_list:
            process_module(desc)

def handle_module_upgrade_request(controller, module_id, pipeline):
    global _remap, _controller, _pipeline
    if _remap is None:
        _remap = UpgradePackageRemap()
        remap = UpgradeModuleRemap(None, '1.0.0', '1.0.0',
                                   module_name='vtkInteractionHandler')
        remap.add_remap('src_port_remap', 'self', 'Instance')
        _remap.add_module_remap(remap)

    _controller = controller
    _pipeline = pipeline
    module_name = pipeline.modules[module_id].name
    if not _remap.has_module_remaps(module_name):
        build_remap(module_name)
    return UpgradeWorkflowHandler.remap_module(controller, module_id, pipeline,
                                              _remap)

