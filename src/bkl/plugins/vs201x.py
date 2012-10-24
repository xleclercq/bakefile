#
#  This file is part of Bakefile (http://www.bakefile.org)
#
#  Copyright (C) 2011-2012 Vaclav Slavik
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to
#  deal in the Software without restriction, including without limitation the
#  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
#  sell copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
#  IN THE SOFTWARE.
#

import codecs

import bkl.compilers
import bkl.expr
from bkl.io import OutputFile, EOL_WINDOWS

from bkl.plugins.vsbase import *
from bkl.expr import concat


# TODO: Put more content into this class, use it properly
class VS2010Project(VSProjectBase):
    """
    """
    version = 10

    def __init__(self, name, guid, projectfile, deps, configs, source_pos=None):
        self.name = name
        self.guid = guid
        self.projectfile = projectfile
        self.dependencies = deps
        self.configurations = configs
        self.source_pos = source_pos



class VS201xToolsetBase(VSToolsetBase):
    """Base class for VS2010 and VS2012 toolsets."""

    #: Extension of format files
    proj_extension = "vcxproj"

    #: PlatformToolset property
    platform_toolset = None

    def gen_for_target(self, target, project):
        rc_files = []
        cl_files = []
        for sfile in target.sources:
            ext = sfile.filename.get_extension()
            # TODO: share this code with VS200x
            # FIXME: make this more solid
            if ext == 'rc':
                rc_files.append(sfile)
            else:
                cl_files.append(sfile)

        root = Node("Project")
        root["DefaultTargets"] = "Build"
        root["ToolsVersion"] = "4.0"
        root["xmlns"] = "http://schemas.microsoft.com/developer/msbuild/2003"

        n_configs = Node("ItemGroup", Label="ProjectConfigurations")
        for cfg in target.configurations:
            n = Node("ProjectConfiguration", Include="%s|Win32" % cfg.name)
            n.add("Configuration", cfg.name)
            n.add("Platform", "Win32")
            n_configs.add(n)
        root.add(n_configs)

        n_globals = Node("PropertyGroup", Label="Globals")
        self._add_extra_options_to_node(target, n_globals)
        n_globals.add("ProjectGuid", "{%s}" % project.guid)
        n_globals.add("Keyword", "Win32Proj")
        n_globals.add("RootNamespace", target.name)
        n_globals.add("ProjectName", target.name)
        self._add_VCTargetsPath(n_globals)
        root.add(n_globals)

        root.add("Import", Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props")

        for cfg in target.configurations:
            n = Node("PropertyGroup", Label="Configuration")
            self._add_extra_options_to_node(cfg, n)
            n["Condition"] = "'$(Configuration)|$(Platform)'=='%s|Win32'" % cfg.name
            if is_program(target):
                n.add("ConfigurationType", "Application")
            elif is_library(target):
                n.add("ConfigurationType", "StaticLibrary")
            elif is_dll(target):
                n.add("ConfigurationType", "DynamicLibrary")
            else:
                assert False, "this code should only be called for supported target types"

            n.add("UseDebugLibraries", cfg.is_debug)
            if cfg["win32-unicode"]:
                n.add("CharacterSet", "Unicode")
            else:
                n.add("CharacterSet", "MultiByte")
            if self.platform_toolset:
                n.add("PlatformToolset", self.platform_toolset)
            root.add(n)

        root.add("Import", Project="$(VCTargetsPath)\\Microsoft.Cpp.props")
        root.add("ImportGroup", Label="ExtensionSettings")

        for cfg in target.configurations:
            n = Node("ImportGroup", Label="PropertySheets")
            n["Condition"] = "'$(Configuration)|$(Platform)'=='%s|Win32'" % cfg.name
            n.add("Import",
                  Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props",
                  Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')",
                  Label="LocalAppDataPlatform")
            root.add(n)

        root.add("PropertyGroup", Label="UserMacros")

        for cfg in target.configurations:
            n = Node("PropertyGroup")
            self._add_extra_options_to_node(cfg, n)
            if not is_library(target):
                n.add("LinkIncremental", cfg.is_debug)
            targetname = cfg["basename"]
            if targetname != target.name:
                n.add("TargetName", targetname)
            if is_module_dll(target):
                n.add("IgnoreImportLibrary", True)
            if target.is_variable_explicitly_set("outputdir"):
                n.add("OutDir", concat(cfg["outputdir"], "\\"))
            if self.needs_custom_intermediate_dir(target):
                n.add("IntDir", concat(self.get_builddir_for(target), "\\$(ProjectName)\\"))
            if n.has_children():
                n["Condition"] = "'$(Configuration)|$(Platform)'=='%s|Win32'" % cfg.name
            root.add(n)

        for cfg in target.configurations:
            n = Node("ItemDefinitionGroup")
            n["Condition"] = "'$(Configuration)|$(Platform)'=='%s|Win32'" % cfg.name
            n_cl = Node("ClCompile")
            self._add_extra_options_to_node(cfg, n_cl)
            n_cl.add("WarningLevel", "Level3")
            if cfg.is_debug:
                n_cl.add("Optimization", "Disabled")
            else:
                n_cl.add("Optimization", "MaxSpeed")
                n_cl.add("FunctionLevelLinking", True)
                n_cl.add("IntrinsicFunctions", True)
            std_defs = self.get_std_defines(target, cfg)
            std_defs.append("%(PreprocessorDefinitions)")
            n_cl.add("PreprocessorDefinitions", list(cfg["defines"]) + std_defs)
            n_cl.add("MultiProcessorCompilation", True)
            n_cl.add("MinimalRebuild", False)
            n_cl.add("AdditionalIncludeDirectories", cfg["includedirs"])

            crt = "MultiThreaded"
            if cfg.is_debug:
                crt += "Debug"
            if cfg["win32-crt-linkage"] == "dll":
                crt += "DLL"
            n_cl.add("RuntimeLibrary", crt)

            # Currently we don't make any distinction between preprocessor, C
            # and C++ flags as they're basically all the same at MSVS level
            # too and all go into the same place in the IDE and same
            # AdditionalOptions node in the project file.
            all_cflags = VSList(" ", cfg["compiler-options"],
                                     cfg["c-compiler-options"],
                                     cfg["cxx-compiler-options"])
            if all_cflags:
                all_cflags.append("%(AdditionalOptions)")
                n_cl.add("AdditionalOptions", all_cflags)

            n.add(n_cl)

            if rc_files:
                n_res = Node("ResourceCompile")
                self._add_extra_options_to_node(cfg, n_res)
                n_res.add("AdditionalIncludeDirectories", cfg["includedirs"])
                std_defs = []
                if cfg["win32-unicode"]:
                    std_defs.append("_UNICODE")
                    std_defs.append("UNICODE")
                std_defs.append("%(PreprocessorDefinitions)")
                n_res.add("PreprocessorDefinitions", list(cfg["defines"]) + std_defs)
                n.add(n_res)

            n_link = Node("Link")
            self._add_extra_options_to_node(cfg, n_link)
            n.add(n_link)
            if is_program(target) and target["win32-subsystem"] == "console":
                n_link.add("SubSystem", "Console")
            else:
                n_link.add("SubSystem", "Windows")
            n_link.add("GenerateDebugInformation", True)
            if not cfg.is_debug:
                n_link.add("EnableCOMDATFolding", True)
                n_link.add("OptimizeReferences", True)
            if not is_library(target):
                libdirs = VSList(";", target.type.get_libdirs(cfg))
                if libdirs:
                    libdirs.append("%(AdditionalLibraryDirectories)")
                    n_link.add("AdditionalLibraryDirectories", libdirs)
                ldflags = VSList(" ", target.type.get_link_options(cfg))
                if ldflags:
                    ldflags.append("%(AdditionalOptions)")
                    n_link.add("AdditionalOptions", ldflags)
            libs = cfg["libs"]
            if libs:
                addlibs = VSList(";", ("%s.lib" % x.as_py() for x in libs))
                addlibs.append("%(AdditionalDependencies)")
                if is_library(target):
                    n_lib = Node("Lib")
                    self._add_extra_options_to_node(cfg, n_lib)
                    n.add(n_lib)
                    n_lib.add("AdditionalDependencies", addlibs)
                else:
                    n_link.add("AdditionalDependencies", addlibs)
            pre_build = cfg["pre-build-commands"]
            if pre_build:
                n_script = Node("PreBuildEvent")
                n_script.add("Command", VSList("\n", pre_build))
                n.add(n_script)
            post_build = cfg["post-build-commands"]
            if post_build:
                n_script = Node("PostBuildEvent")
                n_script.add("Command", VSList("\n", post_build))
                n.add(n_script)
            root.add(n)

        # Source files:
        items = Node("ItemGroup")
        root.add(items)
        cl_files_map = self.disambiguate_intermediate_file_names(cl_files)
        for sfile in cl_files:
            ext = sfile.filename.get_extension()
            # TODO: share this code with VS200x
            # FIXME: make this more solid
            if ext in ['cpp', 'cxx', 'cc', 'c']:
                n_cl_compile = Node("ClCompile", Include=sfile.filename)
            else:
                # FIXME: handle both compilation into cpp and c files
                genfiletype = bkl.compilers.CxxFileType.get()
                genname = bkl.expr.PathExpr([bkl.expr.LiteralExpr(sfile.filename.get_basename())],
                                            bkl.expr.ANCHOR_BUILDDIR,
                                            pos=sfile.filename.pos).change_extension("cpp")

                ft_from = bkl.compilers.get_file_type(ext)
                compiler = bkl.compilers.get_compiler(self, ft_from, genfiletype)

                customBuild = Node("CustomBuild", Include=sfile.filename)
                customBuild.add("Command", VSList("\n", compiler.commands(self, target, sfile.filename, genname)))
                customBuild.add("Outputs", genname)
                items.add(customBuild)
                n_cl_compile = Node("ClCompile", Include=genname)
            # Handle files with custom object name:
            if sfile in cl_files_map:
                n_cl_compile.add("ObjectFileName",
                                 concat("$(IntDir)\\", cl_files_map[sfile], ".obj"))
            self._add_per_file_options(sfile, n_cl_compile)
            items.add(n_cl_compile)

        # Headers files:
        if target.headers:
            items = Node("ItemGroup")
            root.add(items)
            for sfile in target.headers:
                items.add("ClInclude", Include=sfile.filename)

        # Resources:
        if rc_files:
            items = Node("ItemGroup")
            root.add(items)
            rc_files_map = self.disambiguate_intermediate_file_names(rc_files)
            for sfile in rc_files:
                n_rc_compile = Node("ResourceCompile", Include=sfile.filename)
                # Handle files with custom object name:
                if sfile in rc_files_map:
                    n_rc_compile.add("ResourceOutputFileName",
                                     concat("$(IntDir)\\", rc_files_map[sfile], ".res"))
                self._add_per_file_options(sfile, n_rc_compile)
                items.add(n_rc_compile)

        # Dependencies:
        target_deps = target["deps"].as_py()
        if target_deps:
            refs = Node("ItemGroup")
            root.add(refs)
            for dep_id in target_deps:
                dep = target.project.get_target(dep_id)
                dep_prj = self.get_project_object(dep)
                depnode = Node("ProjectReference", Include=dep_prj.projectfile)
                depnode.add("Project", "{%s}" % dep_prj.guid.lower())
                refs.add(depnode)

        root.add("Import", Project="$(VCTargetsPath)\\Microsoft.Cpp.targets")
        root.add("ImportGroup", Label="ExtensionTargets")

        filename = project.projectfile.as_native_path_for_output(target)
        paths_info = self.get_project_paths_info(target, project)

        f = OutputFile(filename, EOL_WINDOWS,
                       creator=self, create_for=target)
        f.write(codecs.BOM_UTF8)
        f.write(XmlFormatter(paths_info).format(root))
        f.commit()
        self._write_filters_file_for(filename)


    def _add_VCTargetsPath(self, node):
        pass

    def _add_extra_options_to_node(self, target, node):
        """Add extra native options specified in vs2010.option.* properties."""
        try:
            scope = node["Label"]
        except KeyError:
            if node.name == "PropertyGroup":
                scope = ""
            else:
                scope = node.name
        for key, value in self.collect_extra_options_for_node(target, scope):
            node.add(key, value)


    def _add_per_file_options(self, srcfile, node):
        """Add options that are set on per-file basis."""
        # TODO: add regular options such as 'defines' here too, not just
        #       the vsXXXX.option.* overrides
        for cfg in srcfile.configurations:
            cond = "'$(Configuration)|$(Platform)'=='%s|Win32'" % cfg.name
            for key, value in self.collect_extra_options_for_node(srcfile, node.name, inherit=False):
                node.add(Node(key, value, Condition=cond))


    def _write_filters_file_for(self, filename):
        f = OutputFile(filename + ".filters", EOL_WINDOWS,
                       creator=self, create_for=filename)
        f.write("""\
<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
    <Filter Include="Source Files">
      <UniqueIdentifier>{4FC737F1-C7A5-4376-A066-2A32D752A2FF}</UniqueIdentifier>
      <Extensions>cpp;c;cc;cxx;def;odl;idl;hpj;bat;asm;asmx</Extensions>
    </Filter>
    <Filter Include="Header Files">
      <UniqueIdentifier>{93995380-89BD-4b04-88EB-625FBE52EBFB}</UniqueIdentifier>
      <Extensions>h;hpp;hxx;hm;inl;inc;xsd</Extensions>
    </Filter>
    <Filter Include="Resource Files">
      <UniqueIdentifier>{67DA6AB6-F800-4c08-8B7A-83BB121AAD01}</UniqueIdentifier>
      <Extensions>rc;ico;cur;bmp;dlg;rc2;rct;bin;rgs;gif;jpg;jpeg;jpe;resx;tiff;tif;png;wav;mfcribbon-ms</Extensions>
    </Filter>
  </ItemGroup>
</Project>
""")
        f.commit()



class VS2010Solution(VSSolutionBase):
    format_version = "11.00"
    human_version = "2010"

    def write_header(self, file):
        file.write(codecs.BOM_UTF8)
        file.write("\n")
        super(VS2010Solution, self).write_header(file)


class VS2010Toolset(VS201xToolsetBase):
    """
    Visual Studio 2010.


    Special properties
    ------------------
    In addition to the properties described below, it's possible to specify any
    of the ``vcxproj`` properties directly in a bakefile. To do so, you have to
    set specially named variables on the target.

    The variables are prefixed with ``vs2010.option.``, followed by node name and
    property name. The following nodes are supported:

      - ``vs2010.option.Globals.*``
      - ``vs2010.option.Configuration.*``
      - ``vs2010.option.*`` (this is the unnamed ``PropertyGroup`` with
        global settings such as ``TargetName``)
      - ``vs2010.option.ClCompile.*``
      - ``vs2010.option.ResourceCompile.*``
      - ``vs2010.option.Link.*``
      - ``vs2010.option.Lib.*``

    These variables can be used in several places in bakefiles:

      - In targets, to applied them as project's global settings.
      - In modules, to apply them to all projects in the module and its submodules.
      - On per-file basis, to modify file-specific settings.

    Examples:

    .. code-block:: bkl

        vs2010.option.GenerateManifest = false;
        vs2010.option.Link.CreateHotPatchableImage = Enabled;

        crashrpt.cpp::vs2010.option.ClCompile.ExceptionHandling = Async;
    """
    name = "vs2010"

    version = 10
    proj_versions = [10]
    # don't set to "v100" because vs2010 doesn't explicitly set it by default:
    platform_toolset = None
    Solution = VS2010Solution
    Project = VS2010Project



class VS2012Solution(VS2010Solution):
    format_version = "12.00"
    human_version = "2012"


class VS2012Project(VS2010Project):
    version = 11


class VS2012Toolset(VS201xToolsetBase):
    """
    Visual Studio 2012.


    Special properties
    ------------------
    This toolset supports the same special properties that
    :ref:`ref_toolset_vs2010`. The only difference is that they are prefixed
    with ``vs2012.option.`` instead of ``vs2010.option.``, i.e. the nodes are:

      - ``vs2012.option.Globals.*``
      - ``vs2012.option.Configuration.*``
      - ``vs2012.option.*`` (this is the unnamed ``PropertyGroup`` with
        global settings such as ``TargetName``)
      - ``vs2012.option.ClCompile.*``
      - ``vs2010.option.ResourceCompile.*``
      - ``vs2012.option.Link.*``
      - ``vs2012.option.Lib.*``

    """

    name = "vs2012"

    version = 11
    proj_versions = [10, 11]
    platform_toolset = "v110"
    Solution = VS2012Solution
    Project = VS2012Project

    def _add_VCTargetsPath(self, node):
        node.add(Node("VCTargetsPath",
                      "$(VCTargetsPath11)",
                      Condition="'$(VCTargetsPath11)' != '' and '$(VSVersion)' == '' and $(VisualStudioVersion) == ''"))