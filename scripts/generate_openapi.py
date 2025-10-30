
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
SECTIONS_DIR = BASE_DIR / "sections"
SPEC_DIR = BASE_DIR / "spec"

CODE_BLOCK_RE = re.compile(r"```(\w+)?\n(.*?)\n```", re.DOTALL)
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}


def load_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("\n---\n", 2)
        if len(parts) == 3:
            return parts[2]
        else:
            end = text.find("\n---\n", 3)
            if end != -1:
                return text[end + 5 :]
    return text


def parse_markdown_structure(path: Path) -> Dict[str, Any]:
    text = load_markdown(path)
    lines = text.splitlines()
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            current = {"level": level, "title": title, "lines": []}
            sections.append(current)
        else:
            if current is None:
                current = {"level": 0, "title": "__intro__", "lines": []}
                sections.append(current)
            current["lines"].append(line)
    return {"sections": sections}


def section_text(section: Dict[str, Any]) -> str:
    raw_lines = section.get("lines", [])
    cleaned = []
    for line in raw_lines:
        if line.strip().startswith("{:"):
            continue
        cleaned.append(line.rstrip())
    return "\n".join(cleaned).strip()


def get_first_level_title(structure: Dict[str, Any]) -> str:
    for section in structure["sections"]:
        if section["level"] == 1:
            return section["title"].strip()
    return ""


def get_intro_text(structure: Dict[str, Any]) -> str:
    intro_lines: List[str] = []
    started = False
    for section in structure["sections"]:
        if section["level"] == 1 and not started:
            intro_lines.append(section_text(section))
            started = True
            continue
        if started:
            if section["level"] <= 1:
                intro_lines.append(section_text(section))
            else:
                break
    intro = "\n".join([part for part in intro_lines if part])
    return intro.strip()


def find_section(structure: Dict[str, Any], title: str) -> Optional[Dict[str, Any]]:
    for sec in structure["sections"]:
        if sec["title"].strip().lower() == title.strip().lower():
            return sec
    return None


def extract_code_blocks(text: str) -> List[Dict[str, Any]]:
    blocks = []
    for match in CODE_BLOCK_RE.finditer(text):
        lang = (match.group(1) or "").strip().lower()
        code = match.group(2)
        blocks.append({"language": lang, "code": code})
    return blocks


def strip_json_comments(source: str) -> str:
    result = []
    in_string = False
    escape = False
    i = 0
    length = len(source)
    while i < length:
        ch = source[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue
        if ch == '/' and i + 1 < length:
            nxt = source[i + 1]
            if nxt == '/':
                i += 2
                while i < length and source[i] not in '\r\n':
                    i += 1
                continue
            if nxt == '*':
                i += 2
                while i + 1 < length and not (source[i] == '*' and source[i + 1] == '/'):
                    i += 1
                i += 2
                continue
        result.append(ch)
        i += 1
    return "".join(result)


def sanitize_json(example: str) -> Optional[Any]:
    cleaned = strip_json_comments(example)
    cleaned = cleaned.strip()
    cleaned = re.sub(r",\s*(?=[}\]])", ",", cleaned)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def extract_json_examples_from_text(text: str) -> List[Any]:
    examples: List[Any] = []
    for block in extract_code_blocks(text):
        lang = block["language"]
        code = block["code"]
        if lang == "json" or (not lang and code.strip().startswith("{")):
            parsed = sanitize_json(code)
            if parsed is not None:
                examples.append(parsed)
        elif lang == "bash":
            for payload in re.findall(r"-d\s+'(\{.*?\})'", code, flags=re.DOTALL):
                parsed = sanitize_json(payload)
                if parsed is not None:
                    examples.append(parsed)
    return examples


def make_schema_name(title: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", " ", title).title().replace(" ", "")
    if not clean:
        clean = "Entity"
    return clean


def format_yaml(value: Any, indent: int = 0) -> str:
    spaces = " " * indent
    if isinstance(value, dict):
        if not value:
            return spaces + "{}"
        lines: List[str] = []
        for key, val in value.items():
            key_line = f"{spaces}{key}:"
            if isinstance(val, (dict, list)):
                lines.append(key_line)
                lines.append(format_yaml(val, indent + 2))
            else:
                formatted = format_yaml(val, 0).strip()
                lines.append(f"{key_line} {formatted}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return spaces + "[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{spaces}-")
                lines.append(format_yaml(item, indent + 2))
            else:
                formatted = format_yaml(item, 0).strip()
                lines.append(f"{spaces}- {formatted}")
        return "\n".join(lines)
    if isinstance(value, str):
        if "\n" in value or value.strip() == "":
            return spaces + json.dumps(value)
        if value.lower() in {"true", "false", "null"}:
            return spaces + json.dumps(value)
        if any(ch in value for ch in [":", "-", "#", "{", "}", "[", "]", ",", '"']):
            return spaces + json.dumps(value)
        return spaces + value
    if isinstance(value, bool):
        return spaces + ("true" if value else "false")
    if value is None:
        return spaces + "null"
    return spaces + str(value)


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(format_yaml(data) + "\n")


def build_general_descriptions() -> Dict[str, str]:
    general_structure = parse_markdown_structure(BASE_DIR / "index.md")
    sections = general_structure["sections"]
    text_parts: List[str] = []
    capture = False
    for sec in sections:
        if sec["level"] == 2 and sec["title"].strip().lower() == "general":
            capture = True
        if capture and sec["level"] == 2 and sec["title"].strip().lower() == "sorting":
            text_parts.append(section_text(sec))
            break
        if capture and sec["level"] >= 2:
            text_parts.append(f"## {sec['title']}\n{section_text(sec)}")
    general_text = "\n\n".join(text_parts).strip()

    auth_structure = parse_markdown_structure(BASE_DIR / "authentication.md")
    auth_text = "\n".join(
        section_text(sec)
        for sec in auth_structure["sections"]
        if sec["level"] >= 1
    ).strip()

    entities_structure = parse_markdown_structure(BASE_DIR / "entities.md")
    ids_section = find_section(entities_structure, "Filter `ids`")
    updated_after_section = find_section(entities_structure, "Filter `updated_after`")
    custom_section = find_section(entities_structure, "Filter by Custom Fields – `custom_properties`")
    ids_text = section_text(ids_section) if ids_section else ""
    updated_text = section_text(updated_after_section) if updated_after_section else ""
    custom_text = section_text(custom_section) if custom_section else ""

    custom_fields_structure = parse_markdown_structure(BASE_DIR / "custom_fields.md")
    custom_fields_text = "\n".join(
        section_text(sec) for sec in custom_fields_structure["sections"]
    ).strip()

    return {
        "general": general_text,
        "authentication": auth_text,
        "ids_filter": ids_text,
        "updated_filter": updated_text,
        "custom_filter": custom_text,
        "custom_fields": custom_fields_text,
    }


def build_global_components(descriptions: Dict[str, str]) -> Dict[str, Any]:
    return {
        "securitySchemes": {
            "TokenAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "Authorization",
                "description": descriptions["authentication"],
            }
        },
        "parameters": {
            "Page": {
                "name": "page",
                "in": "query",
                "description": "Pagination support as described in the general documentation.",
                "schema": {"type": "integer", "minimum": 1},
            },
            "PerPage": {
                "name": "per_page",
                "in": "query",
                "description": "Number of items per page for paginated responses.",
                "schema": {"type": "integer", "minimum": 1},
            },
            "SortBy": {
                "name": "sort_by",
                "in": "query",
                "description": "Sorting is controlled by the `sort_by` query parameter. Provide the field name and optional order (asc or desc).",
                "schema": {"type": "string"},
            },
            "Ids": {
                "name": "ids",
                "in": "query",
                "description": descriptions["ids_filter"],
                "schema": {"type": "string"},
            },
            "UpdatedAfter": {
                "name": "updated_after",
                "in": "query",
                "description": descriptions["updated_filter"],
                "schema": {"type": "string", "format": "date-time"},
            },
            "CustomProperties": {
                "name": "custom_properties",
                "in": "query",
                "description": descriptions["custom_filter"],
                "schema": {"type": "object", "additionalProperties": True},
                "style": "deepObject",
                "explode": True,
            },
        },
        "schemas": {
            "ErrorResponse": {
                "type": "object",
                "description": "Generic error response body.",
                "properties": {
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                },
                "additionalProperties": True,
            }
        },
    }


def summarize_text(text: str) -> str:
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return sentences[0] if sentences else text.strip()


def build_operation_id(method: str, path: str, entity_name: str) -> str:
    cleaned_path = re.sub(r"[{}]", "", path.replace("/", " "))
    words = re.split(r"\s+", cleaned_path.strip())
    camel = "".join(word.title() for word in words if word)
    return method.lower() + camel + entity_name


def build_spec_for_file(path: Path, descriptions: Dict[str, str]) -> Dict[str, Any]:
    structure = parse_markdown_structure(path)
    title = get_first_level_title(structure)
    if not title:
        title = path.stem.replace("_", " ").title()
    intro = get_intro_text(structure)
    attributes_section = find_section(structure, "Attributes")
    attributes_text = section_text(attributes_section) if attributes_section else ""
    attribute_examples = extract_json_examples_from_text(section_text(attributes_section)) if attributes_section else []

    entity_schema_name = make_schema_name(title)

    schema_example = attribute_examples[0] if attribute_examples else None
    schema_description_parts: List[str] = []
    if attributes_text:
        schema_description_parts.append(attributes_text)
    if descriptions["custom_fields"]:
        schema_description_parts.append("Custom fields reference:\n" + descriptions["custom_fields"])
    schema_description = "\n\n".join([part for part in schema_description_parts if part]).strip()

    global_components = build_global_components(descriptions)

    spec: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{title} API",
            "version": "1.0.0",
            "description": "\n\n".join(filter(None, [intro, descriptions["general"]])),
        },
        "servers": [
            {"url": "https://{domain}.mocoapp.com/api/v1", "description": "Base server URL for the MOCO API."}
        ],
        "tags": [
            {
                "name": title,
                "description": intro or title,
            }
        ],
        "components": global_components,
        "security": [{"TokenAuth": []}],
        "paths": {},
    }

    spec_schemas = spec["components"].setdefault("schemas", {})
    spec_schemas[entity_schema_name] = {
        "type": "object",
        "description": schema_description or intro or title,
    }
    if schema_example is not None:
        spec_schemas[entity_schema_name]["example"] = schema_example

    for sec in structure["sections"]:
        if sec["level"] != 2:
            continue
        heading = sec["title"].strip()
        parts = heading.split(" ", 1)
        if parts and parts[0].upper() in HTTP_METHODS and len(parts) == 2:
            method = parts[0].lower()
            path_expr = parts[1].strip()
            op_description = section_text(sec)
            op_summary = heading
            op: Dict[str, Any] = {
                "summary": op_summary,
                "description": op_description,
                "tags": [title],
                "security": [{"TokenAuth": []}],
            }
            if method == "get" and "{" not in path_expr:
                op["parameters"] = [
                    {"$ref": "#/components/parameters/Ids"},
                    {"$ref": "#/components/parameters/UpdatedAfter"},
                    {"$ref": "#/components/parameters/CustomProperties"},
                    {"$ref": "#/components/parameters/Page"},
                    {"$ref": "#/components/parameters/PerPage"},
                    {"$ref": "#/components/parameters/SortBy"},
                ]
            responses: Dict[str, Any] = {}
            if method == "get" and "{" not in path_expr:
                response_schema: Any = {"type": "array", "items": {"$ref": f"#/components/schemas/{entity_schema_name}"}}
            else:
                response_schema = {"$ref": f"#/components/schemas/{entity_schema_name}"}
            examples = extract_json_examples_from_text(op_description)
            if method == "get":
                response_code = "200"
                response_entry: Dict[str, Any] = {
                    "description": summarize_text(op_description) or "Successful response",
                    "content": {
                        "application/json": {
                            "schema": response_schema
                        }
                    }
                }
                if examples:
                    example_value = examples[0]
                    if isinstance(response_schema, dict) and response_schema.get("type") == "array" and not isinstance(example_value, list):
                        example_value = [example_value]
                    response_entry["content"]["application/json"]["examples"] = {
                        "example": {"value": example_value}
                    }
                elif schema_example is not None:
                    example_value = schema_example
                    if isinstance(response_schema, dict) and response_schema.get("type") == "array":
                        example_value = [schema_example]
                    response_entry.setdefault("content", {}).setdefault("application/json", {}).setdefault("examples", {})[
                        "example"
                    ] = {"value": example_value}
                responses[response_code] = response_entry
            elif method == "post":
                response_entry = {
                    "description": summarize_text(op_description) or "Created",
                    "content": {
                        "application/json": {
                            "schema": response_schema
                        }
                    }
                }
                if examples:
                    response_entry["content"]["application/json"]["examples"] = {
                        "example": {"value": examples[-1]}
                    }
                elif schema_example is not None:
                    response_entry["content"]["application/json"]["examples"] = {
                        "example": {"value": schema_example}
                    }
                responses["201"] = response_entry
            elif method in {"put", "patch"}:
                response_entry = {
                    "description": summarize_text(op_description) or "Updated",
                    "content": {
                        "application/json": {
                            "schema": response_schema
                        }
                    }
                }
                if examples:
                    response_entry["content"]["application/json"]["examples"] = {
                        "example": {"value": examples[-1]}
                    }
                elif schema_example is not None:
                    response_entry["content"]["application/json"]["examples"] = {
                        "example": {"value": schema_example}
                    }
                responses["200"] = response_entry
            elif method == "delete":
                responses["204"] = {"description": summarize_text(op_description) or "Deleted"}
            responses["default"] = {
                "description": "Error response",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                }
            }
            op["responses"] = responses

            if method in {"post", "put", "patch"}:
                request_examples = extract_json_examples_from_text(op_description)
                request_example = request_examples[0] if request_examples else schema_example
                if request_example is not None:
                    op["requestBody"] = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{entity_schema_name}"},
                                "examples": {
                                    "example": {"value": request_example}
                                }
                            }
                        }
                    }
            op["operationId"] = build_operation_id(method, path_expr, entity_schema_name)
            spec["paths"].setdefault(path_expr, {})[method] = op
    return spec


def merge_specs(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not specs:
        return {}
    descriptions = build_general_descriptions()
    global_components = build_global_components(descriptions)
    merged: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "MOCO API",
            "version": "1.0.0",
            "description": descriptions["general"],
        },
        "servers": [
            {"url": "https://{domain}.mocoapp.com/api/v1", "description": "Base server URL for the MOCO API."}
        ],
        "tags": [],
        "paths": {},
        "components": global_components,
        "security": [{"TokenAuth": []}],
    }
    tags_seen = set()
    for spec in specs:
        for tag in spec.get("tags", []):
            name = tag.get("name")
            if name and name not in tags_seen:
                merged["tags"].append(tag)
                tags_seen.add(name)
        for path, methods in spec.get("paths", {}).items():
            merged["paths"].setdefault(path, {}).update(methods)
        spec_components = spec.get("components", {})
        merged_components = merged.setdefault("components", {})
        for comp_key, comp_value in spec_components.items():
            if comp_key not in merged_components:
                merged_components[comp_key] = comp_value
                continue
            if isinstance(comp_value, dict):
                for name, definition in comp_value.items():
                    merged_components[comp_key][name] = definition
    return merged


def main() -> None:
    descriptions = build_general_descriptions()
    specs: List[Dict[str, Any]] = []
    for md_file in sorted(SECTIONS_DIR.rglob("*.md")):
        spec = build_spec_for_file(md_file, descriptions)
        rel = md_file.relative_to(SECTIONS_DIR)
        out_path = SPEC_DIR / rel.with_suffix(".yaml")
        write_yaml(out_path, spec)
        specs.append(spec)
    merged = merge_specs(specs)
    write_yaml(SPEC_DIR / "moco-api.yaml", merged)


if __name__ == "__main__":
    main()
