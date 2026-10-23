"""Validate imported input schemas without retrieving network resources."""

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import NoSuchResource


def deny_resource(uri):
    raise NoSuchResource(ref=uri)


def validate_instance(schema, value):
    Draft202012Validator(schema, registry=Registry(retrieve=deny_resource)).validate(value)


def check_schema(schema):
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise ValueError("외부 스키마 참조는 지원하지 않습니다.")
                if key not in {"$id", "$schema"}:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(schema)
    Draft202012Validator.check_schema(schema)
