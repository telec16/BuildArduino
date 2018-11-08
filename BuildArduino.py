#
#    build_arduino.py - build, link and upload sketches script for Arduino
#    ## Now works with Python3 & Windows !
#    Copyright (c) 2010 Ben Sasson.  All right reserved.
#    Copyright (c) 2018 Loup Plantevin.  All right reserved.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import argparse
import pathlib
import subprocess
import shutil
import sys

BUILD_DIR_NAME = '.build'

EXITCODE_OK = 0
EXITCODE_NO_UPLOAD_DEVICE = 1
EXITCODE_NO_WPROGRAM = 2
EXITCODE_NO_AVR_PATH = 3
EXITCODE_INVALID_LIB = 4
EXITCODE_INVALID_INCLUDE = 5

BOARD = 'uno'
CPU_CLOCK = 16000000
ARCH = 'atmega328p'
ENV_VERSION = 18
BAUD = 115200
CORE = 'arduino'

NULL_PATH = pathlib.Path('')

COMPILERS = {
    '.c': 'avr-gcc',
    '.S': 'avr-gcc',
    '.cpp': 'avr-g++',
    '.h': 'header',
    '.ino': 'arduino',
    '.pde': 'arduino'
}

BOARDS = {
    'uno': 'standard',
    'leonardo': 'leonardo',
    'mega': 'mega',
    'micro': 'micro',
    'nano': 'micro',
    'pro': 'micro'
}


def check_dir(dir_str: str, exitcode: int, exitstring: str, must_exist: bool = True):
    from string import Template

    path = dir_str and pathlib.Path(dir_str).resolve()
    if path is None and not must_exist:
        return None
    if path is None \
            or not path.exists() \
            or not path.is_dir():
        raise ValueError(exitcode, Template(exitstring).safe_substitute(path=path))

    return path


def _print_separator(sep='=', title='', default_width=100):
    import os

    try:
        width = os.get_terminal_size().columns or default_width
    except OSError:
        width = default_width
    print(f'{title:{sep}^{width}}')


def _exec(cmd: list, *, debug=True, valid_exitcode=0, simulate=False):
    if debug or simulate:
        _print_separator()
        print(cmd)
    if not simulate:
        exitdata = subprocess.run(cmd)
        if exitdata.returncode != valid_exitcode:
            _print_separator(title=f'exitcode {exitdata.returncode}', sep='-')
            raise Exception(f"Callable error ({exitdata.returncode}) : {exitdata}")


def compile_source(source: pathlib.Path, target_dir: pathlib.Path = None, include_dirs: list = None,
                   avr_path: pathlib.Path = None, arch: str = ARCH, clock: str = CPU_CLOCK, verbose: bool = False,
                   simulate: bool = False) -> pathlib.Path:
    """Compile a single source file, using compiler selected based on file extension and translating arguments
    to valid compiler flags.

    :param source: is the *file* that will be compiled
    :param target_dir: is the *directory* where the object will be (None if same as source)
    :param include_dirs: is a list of Path of all useful inclusions *directories*
    :param avr_path: is the path to the avr tools (None if already in path)
    :param arch: target reference (ex. atmega328p)
    :param clock: target clock speed
    :param verbose: toggle print
    :param simulate: actually send commands

    :return: Path of the object
    """

    if include_dirs is None:
        include_dirs = []

    # Retrieving the compiler from COMPILER dict
    ext = source.suffix
    compiler = COMPILERS.get(ext, None)
    if compiler is None:
        _print_separator()
        print(source, 'has no known compiler')
        _print_separator()
        return NULL_PATH
    if compiler == 'header':
        print(source, 'is a header')
        return NULL_PATH
    if compiler == 'arduino':
        print(source, 'is an Arduino file (hopefully transformed)')
        return NULL_PATH

    if target_dir is None:
        target_dir = source.parent
    # Add '.o' to the extension, then retrieve the name, and put it on the target path
    target = target_dir / (source.name + '.o')

    # create include list, don't use set() because order matters
    dirs = [source.parent]
    for d in include_dirs:
        if d not in dirs:
            dirs.append(d)

    includes = [f'-I{d}' for d in dirs]

    cmd = [compiler if avr_path is None else str(avr_path / compiler),
           *(['-v'] if verbose else []),
           '-c', '-g', '-Os', '-w', '-ffunction-sections', '-fdata-sections',
           f'-mmcu={arch}',
           f'-DF_CPU={clock}L',
           f'-DARDUINO={ENV_VERSION}',
           *includes,
           f'-o{target}',
           str(source)]

    _exec(cmd, simulate=simulate, debug=verbose)
    return target


def compile_directory(directory: pathlib.Path, target_dir: pathlib.Path = None, include_dirs: list = None,
                      avr_path: pathlib.Path = None, arch: str = ARCH, clock: str = CPU_CLOCK, verbose: bool = False,
                      simulate: bool = False) -> list:
    """Compile all source files in a given directory

    :param directory: is the *directory* that will be crawled and compiled (see compile_source)
    :param target_dir: is the *directory* where the object will be (None if same as source)
    :param include_dirs: is a list of Path of all useful inclusions *directories*
    :param avr_path: is the path to the avr tools (None if already in path)
    :param arch: target reference (ex. atmega328p)
    :param clock: target clock speed
    :param verbose: toggle print
    :param simulate: actually send commands

    :return: list of all .obj *files* Path created
    """

    if include_dirs is None:
        include_dirs = []

    obj_files = []
    for filename in directory.iterdir():
        if filename.is_file():
            obj = compile_source(filename, include_dirs=include_dirs, avr_path=avr_path, target_dir=target_dir,
                                 arch=arch, clock=clock, verbose=verbose, simulate=simulate)
            if obj is not NULL_PATH:
                obj_files.append(obj)

    return obj_files


def append_to_archive(obj_file: pathlib.Path, archive: pathlib.Path, avr_path: pathlib.Path = None,
                      verbose: bool = False, simulate: bool = False):
    """Create an .a archive out of .obj files

    :param obj_file: is the *file* that will be archived
    :param archive: is the output *file* where the archive will be
    :param avr_path: is the path to the avr tools (None if already in path)
    :param verbose: toggle print
    :param simulate: actually send commands
    """

    cmd = ['avr-ar' if avr_path is None else str(avr_path / 'avr-ar'),
           'rcs' + ('v' if verbose else ''),
           str(archive),
           str(obj_file)]

    _exec(cmd, simulate=simulate, debug=verbose)


def link(target: pathlib.Path, files: list, avr_path: pathlib.Path = None, arch: str = ARCH, verbose: bool = False,
         simulate: bool = False):
    """Link .obj files to a single .elf file

    :param target: is the .elf *file*
    :param files: is a list of Path of all .obj *files*
    :param avr_path: is the path to the avr tools (None if already in path)
    :param arch: is compilation parameter
    :param verbose: toggle print
    :param simulate: actually send commands
    """

    files = [str(p) for p in files]

    cmd = ['avr-gcc' if avr_path is None else str(avr_path / 'avr-gcc'),
           *(['-v'] if verbose else []),
           '-Os', '-Wl,--gc-sections',
           f'-mmcu={arch}',
           f'-o{target}',
           *files,
           f'-L{target.parent}',
           f'-lm']

    _exec(cmd, simulate=simulate, debug=verbose)


def make_hex(elf: pathlib.Path, avr_path: pathlib.Path = None, verbose: bool = False, simulate: bool = False) -> tuple:
    """Slice elf to .hex (program) end .eep (EEProm) files

    :param elf: is the .elf *file*
    :param avr_path: is the path to the avr tools (None if already in path)
    :param verbose: toggle print
    :param simulate: actually send commands

    :return: (hex_section, eeprom_section), the two *files* Paths
    """

    eeprom_section = elf.with_suffix('.epp')
    hex_section = elf.with_suffix('.hex')

    cmd = ['avr-objcopy' if avr_path is None else str(avr_path / 'avr-objcopy'),
           *(['-v'] if verbose else []),
           '-O', 'ihex',
           '-j', '.eeprom',
           '--set-section-flags=.eeprom=alloc,load', '--no-change-warnings', '--change-section-lma', '.eeprom=0',
           str(elf),
           str(eeprom_section)]

    _exec(cmd, simulate=simulate, debug=verbose)

    cmd = ['avr-objcopy' if avr_path is None else str(avr_path / 'avr-objcopy'),
           *(['-v'] if verbose else []),
           '-O', 'ihex',
           '-R', '.eeprom',
           str(elf),
           str(hex_section)]

    _exec(cmd, simulate=simulate, debug=verbose)

    return hex_section, eeprom_section


def upload(hex_section: pathlib.Path, dev: str, avr_path: pathlib.Path = None, dude_conf: str = None, arch: str = ARCH,
           core: str = CORE, baud: int = BAUD, verbose: bool = False, simulate: bool = False):
    """Upload .hex file to arduino board

    :param hex_section: is the .hex *file*
    :param dev: is the serial Port
    :param avr_path: is the path to the avr tools *directory* (None if already in path)
    :param dude_conf: is the the avr-dude configuration *file*
    :param arch: target reference (ex. atmega328p)
    :param core: target core (arduino)
    :param baud:, are upload parameters
    :param verbose: toggle print
    :param simulate: actually send commands
    """

    cmd = ['avrdude' if avr_path is None else str(avr_path / 'avrdude'),
           *(['-v'] if verbose else []),
           *([f'-C{dude_conf}'] if dude_conf is not None else []),
           f'-p{arch}',
           f'-c{core}',
           f'-P{dev}',
           f'-b{baud}',
           '-D',
           f'-Uflash:w:{hex_section}:i']

    _exec(cmd, simulate=simulate, debug=verbose)


def main(argv):
    print(argv)

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--directory', dest='directory', default='.',
                        help='project directory')
    parser.add_argument('-v', '--verbose', dest='verbose', default=False, action='store_true',
                        help='be verbose')
    parser.add_argument('-r', '--refresh', dest='refresh', default=False, action='store_true',
                        help="delete build folder")
    parser.add_argument('--only-build', dest='only_build', default=False, action='store_true',
                        help="only build, don't upload")
    parser.add_argument('-u', '--upload-port', dest='upload_port', metavar='PORT',
                        help='used PORT to upload code')
    parser.add_argument('-b', '--board', dest='board', default=BOARD, metavar='BOARD',
                        help=f'Arduino board name [{BOARD}]')
    parser.add_argument('-i', '--include', dest='include_dirs', default=[], action='append', metavar='DIRECTORY',
                        help='append DIRECTORY to include list')
    parser.add_argument('-l', '--libraries', dest='libraries', default=[], action='append', metavar='DIRECTORY',
                        help='append DIRECTORY to libraries search & build path')
    parser.add_argument('-W', '--WProgram-dir', dest='wprogram_directory', metavar='DIRECTORY',
                        help='DIRECTORY of Arduino.h and the rest of core files '
                             '(/Arduino/hardware/arduino/avr/cores/arduino/)')
    parser.add_argument('-V', '--Variants-dir', dest='variants_directory', metavar='DIRECTORY',
                        help='DIRECTORY of variants folders '
                             '(/Arduino/hardware/arduino/avr/variants/)')
    parser.add_argument('--avr-path', dest='avr_path', metavar='DIRECTORY',
                        help='DIRECTORY where avr* programs located, '
                             'if not specified will assume found in default search path')
    parser.add_argument('--dude-conf', dest='dude_conf', default=None, metavar='FILE',
                        help='avrdude conf file (.../Arduino/hardware/tools/avr/etc/avrdude.conf), '
                             'if not specified - will assume found in default location')
    parser.add_argument('--simulate', dest='simulate', default=False, action='store_true',
                        help='only simulate commands')
    parser.add_argument(f'--core', dest='core', default=CORE,
                        help='device core name [{CORE}]')
    parser.add_argument(f'--arch', dest='arch', default=ARCH,
                        help='device architecture name [{ARCH}]')
    parser.add_argument('--baud', dest='baud', default=BAUD, type=int,
                        help=f'upload baud rate [{BAUD}]')
    parser.add_argument('--cpu-clock', dest='cpu_clock', default=CPU_CLOCK, metavar='Hz', action='store', type=int,
                        help=f'target device CPU clock [{CPU_CLOCK}]')

    args = parser.parse_args(argv)

    # ################## #
    # ## Testing args ## #
    # ################## #

    core_path = check_dir(args.wprogram_directory, EXITCODE_NO_WPROGRAM,
                          '''WProgram directory was not specified or does not exist [$path]''')
    variant_path = check_dir(args.variants_directory, EXITCODE_NO_WPROGRAM,
                             '''Variants directory was not specified or does not exist [$path]''')

    board = BOARDS.get(args.board, None)
    if board is None:
        board = BOARDS.get(BOARD, None)

    arduino_files = [core_path] + [variant_path / board]

    avr_path = check_dir(args.avr_path, EXITCODE_NO_AVR_PATH,
                         '''avr-path was not specified or does not exist [$path]''', must_exist=False)
    dude_conf = pathlib.Path(args.dude_conf)

    libraries = [check_dir(l, EXITCODE_INVALID_LIB, '''Library does not exist [$path]''') for l in args.libraries]
    include_dirs = [check_dir(l, EXITCODE_INVALID_INCLUDE, '''Include does not exist [$path]''') for l in
                    args.include_dirs]

    # ########### #
    # ## Build ## #
    # ########### #

    # create build directory to store the compilation output files
    main_path = pathlib.Path(args.directory).resolve()
    build_path = main_path / BUILD_DIR_NAME
    print(f'Building in {build_path}...')
    if build_path.exists() and args.refresh:
        print(f'Deleting then creating build folder')
        shutil.rmtree(build_path)
        build_path.mkdir()
    elif not build_path.exists():
        build_path.mkdir()

    # compile arduino core files
    _print_separator(sep='!', title="Compiling Arduino")
    core_obj_files = compile_directory(core_path, build_path, include_dirs=arduino_files, avr_path=avr_path,
                                       arch=args.arch, clock=args.cpu_clock, verbose=args.verbose,
                                       simulate=args.simulate)

    # compile directories passed to program
    _print_separator(sep='!', title="Compiling side files")
    libraries_obj_files = []
    for library in libraries:
        lib = compile_directory(library, build_path, include_dirs=libraries + arduino_files, avr_path=avr_path,
                                arch=args.arch, clock=args.cpu_clock, verbose=args.verbose, simulate=args.simulate)
        libraries_obj_files.extend(lib)

    # change .ino to .cpp (and save paths to delete them afterward)
    _print_separator(sep='!', title="Detecting ino")
    cpp_files = []
    for ino_file in main_path.glob('*.ino'):
        cpp_file = ino_file.with_suffix('.cpp')

        _print_separator(sep='', title=f"Transforming {ino_file} to {cpp_file} ...\n")
        shutil.copy(src=str(ino_file), dst=str(cpp_file))

        cpp_files.append(cpp_file)

    # compile project
    _print_separator(sep='!', title="Compiling Sketch")
    project_obj_files = compile_directory(main_path, build_path,
                                          include_dirs=(include_dirs + libraries + arduino_files), avr_path=avr_path,
                                          arch=args.arch, clock=args.cpu_clock, verbose=args.verbose,
                                          simulate=args.simulate)

    # link project, libraries and core .obj files to a single .elf
    _print_separator(sep='!', title="Linking")
    link_output = build_path / (main_path.name + '.elf')
    link(link_output, project_obj_files + libraries_obj_files + core_obj_files, avr_path=avr_path, verbose=args.verbose,
         simulate=args.simulate)

    hex_section, eeprom_section = make_hex(link_output, avr_path=avr_path, verbose=args.verbose, simulate=args.simulate)

    # Delete previously created files
    for cpp_file in cpp_files:
        _print_separator(sep='', title=f"Deleting {cpp_file} ...\n")
        cpp_file.unlink()

    # ############ #
    # ## Upload ## #
    # ############ #

    if not args.only_build:
        if args.upload_port is None:
            raise ValueError(EXITCODE_NO_UPLOAD_DEVICE, f'no upload device selected')
        _print_separator(sep='!', title="Uploading")
        upload(hex_section, dev=args.upload_port, dude_conf=dude_conf, avr_path=avr_path, arch=args.arch,
               core=args.core, baud=args.baud, verbose=args.verbose, simulate=args.simulate)


if __name__ == '__main__':
    _argv = sys.argv[1:]
    main(_argv)
