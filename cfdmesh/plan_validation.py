"""Validate the emitted scientific tool schema before consuming a mesh attempt.

This deliberately supports only the schema vocabulary used by plan_tool. Unknown
vocabulary is rejected rather than silently weakening validation.
"""
import math
import re


def validate_schema(value,schema,path='$'):
    supported={'type','properties','required','additionalProperties','minProperties','anyOf',
               'enum','minimum','maximum','items','minItems','maxItems','pattern','uniqueItems'}
    if set(schema)-supported:raise ValueError(f'{path}: unsupported schema keyword')
    if 'anyOf' in schema:
        choices=schema['anyOf']
        if isinstance(value,dict) and 'kind' in value:
            matching=[s for s in choices if value['kind'] in s.get('properties',{}).get('kind',{}).get('enum',[])]
            if matching:choices=matching
        errors=[]
        for choice in choices:
            try:validate_schema(value,choice,path);return
            except ValueError as exc:errors.append(str(exc))
        raise ValueError('; '.join(errors[:3]))
    kind=schema.get('type')
    good={'object':isinstance(value,dict),'array':isinstance(value,list),
          'string':isinstance(value,str),'boolean':isinstance(value,bool),
          'number':isinstance(value,(int,float)) and not isinstance(value,bool),
          'integer':isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and int(value)==value}
    if kind and not good.get(kind,False):raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']:raise ValueError(f'{path}: unsupported value {value!r}')
    if kind in ('integer','number'):
        if not math.isfinite(value):raise ValueError(f'{path}: nonfinite number')
        if value<schema.get('minimum',-math.inf) or value>schema.get('maximum',math.inf):raise ValueError(f'{path}: received {value}; allowed interval [{schema.get("minimum",-math.inf)}, {schema.get("maximum",math.inf)}]')
    if kind=='string' and 'pattern' in schema and not re.search(schema['pattern'],value):raise ValueError(f'{path}: invalid name pattern')
    if kind=='object':
        missing=set(schema.get('required',[]))-set(value)
        if missing:raise ValueError(f'{path}: missing {sorted(missing)}')
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False and set(value)-set(props):raise ValueError(f'{path}: unknown fields {sorted(set(value)-set(props))}')
        if len(value)<schema.get('minProperties',0):raise ValueError(f'{path}: empty parameters')
        for key,item in value.items():
            if key in props:validate_schema(item,props[key],f'{path}.{key}')
    if kind=='array':
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',math.inf):raise ValueError(f'{path}: invalid item count')
        if schema.get('uniqueItems') and any(a==b for i,a in enumerate(value) for b in value[i+1:]):
            raise ValueError(f'{path}: duplicate items')
        for i,item in enumerate(value):validate_schema(item,schema.get('items',{}),f'{path}[{i}]')


def validate_plan(decision,tool):
    validate_schema(decision,tool['function']['parameters'])
    if not decision['hypothesis'].strip() or not decision['expected_change'].strip():raise ValueError('empty scientific hypothesis or expectation')
    if not decision['actions'] and decision.get('disposition')!='stop':raise ValueError('repair requires at least one action')
    if decision.get('disposition')=='stop' and decision['actions']:raise ValueError('stop cannot execute actions')
    for i,action in enumerate(decision['actions']):
        if not action['why'].strip():raise ValueError(f'actions[{i}]: scientific reason missing')
        if action['kind']=='restore_plan' and i!=0:raise ValueError('restore_plan must be first')
