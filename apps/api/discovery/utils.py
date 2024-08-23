from re import sub

from fastapi.routing import APIRoute


def custom_generate_unique_id(route: APIRoute):
    return f"{camel_case(route.name)}-{route.tags[0]}"


def camel_case(s: str):
    s = sub(r"(_|-)+", " ", s).title().replace(" ", "")
    return "".join([s[0].lower(), s[1:]])
