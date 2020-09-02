import os
import textwrap
import pycparser
from pycparser import c_ast, c_generator, parse_file

AUTO = '# This file is automatically generated'
GRB_DEFINES = {
    'GRB_VERSION': 'int64_t',
    'GRB_SUBVERSION': 'int64_t',
}
SS_DEFINES = {
    '*GxB_IMPLEMENTATION_ABOUT': 'char',
    '*GxB_IMPLEMENTATION_DATE': 'char',
    '*GxB_IMPLEMENTATION_LICENSE': 'char',
    '*GxB_IMPLEMENTATION_NAME': 'char',
    '*GxB_SPEC_ABOUT': 'char',
    '*GxB_SPEC_DATE': 'char',
    'GxB_CHUNK': 'int64_t',
    'GxB_GPU_CHUNK': 'int64_t',
    'GxB_GPU_CONTROL': 'int64_t',
    'GxB_IMPLEMENTATION': 'int64_t',
    'GxB_IMPLEMENTATION_MAJOR': 'int64_t',
    'GxB_IMPLEMENTATION_MINOR': 'int64_t',
    'GxB_IMPLEMENTATION_SUB': 'int64_t',
    'GxB_MKL': 'int64_t',
    'GxB_NTHREADS': 'int64_t',
    'GxB_SPEC_MAJOR': 'int64_t',
    'GxB_SPEC_MINOR': 'int64_t',
    'GxB_SPEC_SUB': 'int64_t',
    'GxB_SPEC_VERSION': 'int64_t',
    'GxB_STDC_VERSION': 'int64_t',
    'GxB_INDEX_MAX': 'uint64_t',
}
SS_SLICING_DEFINES = {
    'GxB_RANGE': 'int64_t',
    'GxB_STRIDE': 'int64_t',
    'GxB_BACKWARDS': 'int64_t',
    'GxB_BEGIN': 'int64_t',
    'GxB_END': 'int64_t',
    'GxB_INC': 'int64_t',
}


def get_basedir():
    thisdir = os.path.dirname(__file__)
    return os.path.join(thisdir, '..')


def pyname(cname, seen=None):
    if cname.startswith('*'):
        cname = cname[1:]
    if cname.startswith('GxB_') or cname.startswith('GrB_'):
        val = cname[4:]
        if seen is not None and val in seen:
            raise ValueError(f'Already seen: {cname}')
        if seen is not None:
            seen.add(val)
        return val
    raise ValueError(f'Unable to create Python name for: {cname}')


class VisitEnumTypedef(c_generator.CGenerator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.results = []

    def visit_Typedef(self, node):
        rv = super().visit_Typedef(node)
        if isinstance(node.type.type, c_ast.Enum):
            self.results.append(rv + ';')
        return rv


def get_ast(filename):
    fake_include = os.path.dirname(pycparser.__file__) + 'utils/fake_libc_include'
    ast = parse_file(filename, cpp_args=f'-I{fake_include}')
    return ast


def get_groups(ast):
    generator = c_generator.CGenerator()
    lines = generator.visit(ast).splitlines()

    seen = set()
    groups = {}
    vals = {x for x in lines if 'extern GrB_Info GxB' in x} - seen
    seen.update(vals)
    groups['GxB methods'] = sorted(vals)

    vals = {x for x in lines if 'extern GrB_Info GrB' in x} - seen
    seen.update(vals)
    groups['GrB methods'] = sorted(vals)

    vals = {x for x in lines if 'extern GrB_Info GB' in x} - seen
    seen.update(vals)
    groups['GB methods'] = sorted(vals)

    missing_methods = {x for x in lines if 'extern GrB_Info ' in x} - seen
    assert not missing_methods

    vals = {x for x in lines if 'extern GrB' in x} - seen
    seen.update(vals)
    groups['GrB objects'] = sorted(vals)

    vals = {x for x in lines if 'extern GxB' in x} - seen
    seen.update(vals)
    groups['GxB objects'] = sorted(vals)

    vals = {x for x in lines if 'extern const' in x and 'GxB' in x} - seen
    seen.update(vals)
    groups['GxB const'] = sorted(vals)

    vals = {x for x in lines if 'extern const' in x and 'GrB' in x} - seen
    seen.update(vals)
    groups['GrB const'] = sorted(vals)

    missing_const = {x for x in lines if 'extern const' in x} - seen
    assert not missing_const

    vals = {x for x in lines if 'typedef' in x and 'GxB' in x and '(' not in x} - seen
    seen.update(vals)
    groups['GxB typedef'] = sorted(vals)

    vals = {x for x in lines if 'typedef' in x and 'GrB' in x and '(' not in x} - seen
    seen.update(vals)
    groups['GrB typedef'] = sorted(vals)

    missing_typedefs = {x for x in lines if 'typedef' in x and 'GB' in x and '(' not in x} - seen
    assert not missing_typedefs
    assert all(x.endswith(';') for x in seen)  # sanity check

    g = VisitEnumTypedef()
    _ = g.visit(ast)
    enums = g.results

    vals = {x for x in enums if '} GrB' in x}
    for val in vals:
        seen.update(val.splitlines())
    groups['GrB typedef enums'] = sorted(vals, key=lambda x: x.rsplit('}', 1)[-1])

    vals = {x for x in enums if '} GxB' in x}
    for val in vals:
        seen.update(val.splitlines())
    groups['GxB typedef enums'] = sorted(vals, key=lambda x: x.rsplit('}', 1)[-1])

    missing_enums = set(enums) - set(groups['GrB typedef enums']) - set(groups['GxB typedef enums'])
    assert not missing_enums

    vals = {x for x in lines if 'typedef' in x and 'GxB' in x} - seen
    seen.update(vals)
    groups['GxB typedef funcs'] = vals

    vals = {x for x in lines if 'typedef' in x and 'GrB' in x} - seen
    assert not vals
    groups['not seen'] = sorted(set(lines) - seen)
    return groups


def get_group_info(groups):
    rv = {}

    def handle_constants(group):
        for line in group:
            extern, const, ctype, cname = line.split(' ')
            assert cname.endswith(';')
            cname = cname[:-1].replace('(void)', '()')
            assert extern == 'extern'
            assert const == 'const'
            info = {
                'ctype': ctype,
                'cname': cname,
                'pyname': pyname(cname),
                'text': line,
            }
            if ctype == 'uint64_t' and cname.startswith('*'):
                info['pycast'] = '<uintptr_t>'
            yield info

    rv['GrB const'] = list(handle_constants(groups['GrB const']))
    rv['GxB const'] = list(handle_constants(groups['GxB const']))

    def handle_objects(group):
        for line in group:
            extern, ctype, cname = line.split(' ')
            assert cname.endswith(';')
            cname = cname[:-1]
            assert extern == 'extern'
            info = {
                'ctype': ctype,
                'cname': cname,
                'pytype': pyname(ctype),
                'pyname': pyname(cname),
                'text': line,
            }
            yield info

    rv['GrB objects'] = list(handle_objects(groups['GrB objects']))
    rv['GxB objects'] = list(handle_objects(groups['GxB objects']))

    def handle_enums(group):
        for text in group:
            typedef, bracket, *fields, cname = text.splitlines()
            assert typedef.strip() == 'typedef enum'
            assert bracket == '{'
            assert cname.startswith('}')
            assert cname.endswith(';')
            cname = cname[1:-1].strip()
            new_fields = []
            for field in fields:
                if field.endswith(','):
                    field = field[:-1]
                field = field.strip()
                cfieldname, eq, val = field.split(' ')
                assert eq == '='
                fieldinfo = {
                    'cname': cfieldname,
                    'pyname': pyname(cfieldname),
                    'value': val,
                    'text': field,
                    'pytype': pyname(cname),
                }
                new_fields.append(fieldinfo)
            info = {
                'cname': cname,
                'pyname': pyname(cname),
                'fields': new_fields,
                'text': text,
            }
            yield info

    rv['GrB typedef enums'] = list(handle_enums(groups['GrB typedef enums']))
    rv['GxB typedef enums'] = list(handle_enums(groups['GxB typedef enums']))

    def handle_typedefs(group):
        for line in group:
            typedef, *ctypes, cname = line.split(' ')
            ctype = ctypes[-1]
            is_struct = ctypes[0] == 'struct'
            # assert is_struct == (len(ctypes) == 2), line
            assert typedef == 'typedef'
            assert cname.endswith(';')
            cname = cname[:-1]
            info = {
                'cname': cname,
                'ctype': ctype,
                'is_struct': is_struct,
                'pyname': pyname(cname),
                'text': line,
            }
            yield info

    rv['GrB typedef'] = list(handle_typedefs(groups['GrB typedef']))
    rv['GxB typedef'] = list(handle_typedefs(groups['GxB typedef']))

    # TODO: 'GB methods', 'GrB methods', 'GxB methods', 'GxB typedef funcs', 'not seen'
    return rv


def get_suitesparse_pxd(groups):
    groups = dict(groups)
    text = [
        AUTO,
        'from libc.stdint cimport int64_t, uint64_t',
        '',
        'cdef extern from "GraphBLAS.h" nogil:',
        '    # #defines',
    ]
    for name, typ in sorted(GRB_DEFINES.items()) + sorted(SS_DEFINES.items(), key=lambda x: (x[1], x[0])):
        text.append(f'    const {typ} {name}')
    text.append('    # slicing #defines')
    for name, typ in sorted(SS_SLICING_DEFINES.items()):
        text.append(f'    const {typ} {name}')

    def handle_typedefs(group):
        for info in group:
            if '_Complex' in info['text']:
                continue
            if info['is_struct']:
                yield f'    ctypedef struct {info["ctype"]}:'
                yield '        pass'
            yield f'    ctypedef {info["ctype"]} {info["cname"]}'

    text.append('')
    text.append('    # GrB typedefs')
    text.extend(handle_typedefs(groups['GrB typedef']))
    text.append('')
    text.append('    # GxB typedefs')
    text.extend(handle_typedefs(groups['GxB typedef']))

    def handle_enums(group):
        for info in group:
            yield f'    ctypedef enum {info["cname"]}:'
            for field in info['fields']:
                yield f'        {field["cname"]}'

    text.append('')
    text.append('    # GrB enums')
    text.extend(handle_enums(groups['GrB typedef enums']))
    text.append('')
    text.append('    # GxB enums')
    text.extend(handle_enums(groups['GxB typedef enums']))

    # print('\n'.join(x['text'] for x in groups['GrB const']))
    def handle_consts(group):
        for info in group:
            yield f'    const {info["ctype"]} {info["cname"]}'

    text.append('')
    text.append('    # GrB consts')
    text.extend(handle_consts(groups['GrB const']))
    text.append('')
    text.append('    # GxB consts')
    text.extend(handle_consts(groups['GxB const']))


    def handle_objects(group):
        for info in group:
            yield f'    {info["ctype"]} {info["cname"]}'

    text.append('')
    text.append('    # GrB objects')
    text.extend(handle_objects(x for x in groups['GrB objects'] if 'GxB' not in x['text']))
    text.append('')
    text.append('    # GrB objects (extended)')
    text.extend(handle_objects(x for x in groups['GrB objects'] if 'GxB' in x['text']))
    text.append('')
    text.append('    # GxB objects')
    text.extend(handle_objects(groups['GxB objects']))

    return '\n'.join(text)


def main(basedir):
    thisdir = os.path.dirname(__file__)
    ast = get_ast(os.path.join(thisdir, 'GraphBLAS-processed.h'))
    groups = get_groups(ast)
    groups = get_group_info(groups)
    pxd = get_suitesparse_pxd(groups)

    filename = os.path.join(basedir, 'cygraphblas_ss', 'graphblas.pxd')
    print(f'Writing {filename}')
    with open(filename, 'w') as f:
        f.write(pxd)

    def handle_lib(objects, enums, is_pyx=False, extra_import=None):
        text = [
            AUTO,
        ]
        if not is_pyx:
            text.append('from cygraphblas.wrappertypes cimport BinaryOp, Descriptor, Monoid, Semiring, UnaryOp, Type')
            text.append('from cygraphblas.wrappertypes.constants cimport Desc_Field, Desc_Value, Info, Mode')
        if extra_import is not None:
            text.append(extra_import)

        text.append('')
        text.append('# Enums')
        for info in sorted(enums, key=lambda x: x['pyname']):
            for field in info['fields']:
                if is_pyx:
                    text.append(f'cdef {field["pytype"]} {field["pyname"]} = {field["pytype"]}._new("{field["cname"]}")')
                else:
                    text.append(f'cdef {field["pytype"]} {field["pyname"]}')

        prev_pytype = None
        for info in objects:
            if info['pytype'] != prev_pytype:
                prev_pytype = info['pytype']
                text.append('')
                text.append(f'# {prev_pytype}')
            if is_pyx:
                text.append(f'cdef {info["pytype"]} {info["pyname"]} = {info["pytype"]}._new("{info["cname"]}")')
            else:
                text.append(f'cdef {info["pytype"]} {info["pyname"]}')
        return text

    def get_enums(group, field_filter):
        rv = []
        for info in group:
            val = dict(info)
            val['fields'] = sorted((val for val in info['fields'] if val['cname'].startswith(field_filter)), key=lambda x: x['pyname'])
            rv.append(val)
        return rv

    group = [info for info in groups['GrB objects'] if 'GxB' not in info['text']]
    enums = get_enums(groups['GrB typedef enums'], 'GrB')
    text = handle_lib(group, enums, is_pyx=False)
    filename = os.path.join(basedir, 'cygraphblas', '_clib.pxd')
    # filename = os.path.join(basedir, 'cygraphblas', '_clib', '__init__.pxd')
    print(f'Writing {filename}')
    with open(filename, 'w') as f:
        f.write('\n'.join(text))

    text = handle_lib(group, enums, is_pyx=True)
    # filename = os.path.join(basedir, 'cygraphblas', '_clib', '__init__.pyx')
    filename = os.path.join(basedir, 'cygraphblas', '_clib.pyx')
    print(f'Writing {filename}')
    with open(filename, 'w') as f:
        f.write('\n'.join(text))

    def handle_lib_object(group, pytype, altimport=None):
        group = [info for info in group if info['pytype'] == pytype]
        text = [
            AUTO,
        ]
        if not group:
            return text
        if altimport is None:
            text.append('from cygraphblas cimport _clib as clib')
        else:
            text.append(altimport)
        text.append('')
        for info in group:
            text.append(f'{info["pyname"]} = clib.{info["pyname"]}')
        return text

    object_info = [
        ('binary', 'BinaryOp'),
        ('descriptor', 'Descriptor'),
        ('monoid', 'Monoid'),
        ('semiring', 'Semiring'),
        ('dtypes', 'Type'),
        ('unary', 'UnaryOp'),
    ]
    for name, pytype in object_info:
        text = handle_lib_object(group, pytype)
        if not text:
            continue
        filename = os.path.join(basedir, 'cygraphblas', 'lib', name, '__init__.pyx')
        print(f'Writing {filename}')
        with open(filename, 'w') as f:
            f.write('\n'.join(text))

    for info in enums:
        text = handle_lib_object(info['fields'], info['pyname'])
        filename = os.path.join(basedir, 'cygraphblas', 'lib', 'constants', info['pyname'].lower(), '__init__.pyx')
        print(f'Writing {filename}')
        with open(filename, 'w') as f:
            f.write('\n'.join(text))

    # Now do SuiteSparse-specific things (in cygraphblas_ss!)
    def handle_init(group, altimport=None):
        text = [
            AUTO,
        ]
        if altimport is None:
            text.append('from cygraphblas cimport _clib as clib')
        else:
            text.append(altimport)
        text.append('from cygraphblas_ss cimport graphblas as ss')
        prev_pytype = None
        for info in group:
            if info['pytype'] != prev_pytype:
                prev_pytype = info['pytype']
                text.append('')
                text.append(f'# {prev_pytype}')
            text.append(f'clib.{info["pyname"]}.ss_obj = ss.{info["cname"]}')
        return text

    grb_enums = []
    for info in enums:
        grb_enums.extend(info['fields'])

    text = handle_init(grb_enums + group)
    filename = os.path.join(basedir, 'cygraphblas_ss', 'initialize.pyx')
    print(f'Writing {filename}')
    with open(filename, 'w') as f:
        f.write('\n'.join(text))

    group = [info for info in groups['GrB objects'] if 'GxB' in info['text']]
    gxb_group = sorted(group + groups['GxB objects'], key=lambda info: info['pytype'])
    extra_import = (
        'from cygraphblas_ss.wrappertypes cimport SelectOp\n'
        'from cygraphblas_ss.wrappertypes.constants cimport Format_Value, Option_Field, Print_Level, Thread_Model'
    )
    enums = (
        get_enums(groups['GrB typedef enums'], 'GxB')
        + get_enums(groups['GxB typedef enums'], 'GxB')
    )
    text = handle_lib(gxb_group, enums, is_pyx=False, extra_import=extra_import)
    filename = os.path.join(basedir, 'cygraphblas_ss', '_clib.pxd')
    print(f'Writing {filename}')
    with open(filename, 'w') as f:
        f.write('\n'.join(text))

    text = handle_lib(gxb_group, enums, is_pyx=True)  #, extra_import=extra_import)
    filename = os.path.join(basedir, 'cygraphblas_ss', '_clib.pyx')
    print(f'Writing {filename}')
    with open(filename, 'w') as f:
        f.write('\n'.join(text))

    # Suitesparse GxB extensions of GrB objects
    altimport = 'from cygraphblas_ss cimport _clib as clib'
    for name, pytype in object_info + [('selectop', 'SelectOp')]:
        text = handle_lib_object(gxb_group, pytype, altimport=altimport)
        filename = os.path.join(basedir, 'cygraphblas_ss', 'lib', f'{name}.pyx')
        print(f'Writing {filename}')
        with open(filename, 'w') as f:
            f.write('\n'.join(text))

    gxb_enums = []
    for info in enums:
        gxb_enums.extend(info['fields'])

    text = handle_init(gxb_enums + gxb_group, altimport=altimport)
    filename = os.path.join(basedir, 'cygraphblas_ss', 'initialize_ss.pyx')
    print(f'Writing {filename}')
    with open(filename, 'w') as f:
        f.write('\n'.join(text))

    for info in enums:
        text = handle_lib_object(info['fields'], info['pyname'], altimport=altimport)
        filename = os.path.join(basedir, 'cygraphblas_ss', 'lib', 'constants', f"{info['pyname'].lower()}.pyx")
        print(f'Writing {filename}')
        with open(filename, 'w') as f:
            f.write('\n'.join(text))


if __name__ == '__main__':
    main(get_basedir())
