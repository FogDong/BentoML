from __future__ import annotations
from copy import deepcopy

import re
import typing as t

import schema as s

from ...utils.metrics import DEFAULT_BUCKET
from ...utils.unflatten import unflatten
from ..helpers import depth
from ..helpers import ensure_iterable_type
from ..helpers import ensure_larger_than
from ..helpers import ensure_larger_than_zero
from ..helpers import ensure_range
from ..helpers import is_valid_ip_address
from ..helpers import rename_fields
from ..helpers import validate_otlp_protocol
from ..helpers import validate_tracing_type

__all__ = ["SCHEMA", "migration"]

TRACING_CFG = {
    "exporter_type": s.Or(s.And(str, s.Use(str.lower), validate_tracing_type), None),
    "sample_rate": s.Or(s.And(float, ensure_range(0, 1)), None),
    "timeout": s.Or(s.And(int, ensure_larger_than_zero), None),
    "max_tag_value_length": s.Or(int, None),
    "excluded_urls": s.Or([str], str, None),
    "zipkin": {
        "endpoint": s.Or(str, None),
        "local_node_ipv4": s.Or(s.Or(s.And(str, is_valid_ip_address), int), None),
        "local_node_ipv6": s.Or(s.Or(s.And(str, is_valid_ip_address), int), None),
        "local_node_port": s.Or(s.And(int, ensure_larger_than_zero), None),
    },
    "jaeger": {
        "protocol": s.Or(
            s.And(str, s.Use(str.lower), lambda d: d in ["thrift", "grpc"]),
            None,
        ),
        "collector_endpoint": s.Or(str, None),
        "thrift": {
            "agent_host_name": s.Or(str, None),
            "agent_port": s.Or(int, None),
            "udp_split_oversized_batches": s.Or(bool, None),
        },
        "grpc": {
            "insecure": s.Or(bool, None),
        },
    },
    "otlp": {
        "protocol": s.Or(s.And(str, s.Use(str.lower), validate_otlp_protocol), None),
        "endpoint": s.Or(str, None),
        "compression": s.Or(
            s.And(str, lambda d: d in {"gzip", "none", "deflate"}), None
        ),
        "http": {
            "certificate_file": s.Or(str, None),
            "headers": s.Or(dict, None),
        },
        "grpc": {
            "insecure": s.Or(bool, None),
            "headers": s.Or(lambda d: isinstance(d, t.Sequence), None),
        },
    },
}
_SERVICE_CONFIG = {
    s.Optional("batching"): {
        s.Optional("enabled"): bool,
        s.Optional("max_batch_size"): s.And(int, ensure_larger_than_zero),
        s.Optional("max_latency_ms"): s.And(int, ensure_larger_than_zero),
    },
    # NOTE: there is a distinction between being unset and None here; if set to 'None'
    # in configuration for a specific runner, it will override the global configuration.
    s.Optional("resources"): s.Or({s.Optional(str): object}, lambda s: s == "system", None),  # type: ignore (incomplete schema typing)
    s.Optional("workers"): s.Or([{"gpus": s.Or(ensure_larger_than_zero, list)}], None),
    s.Optional("traffic"): {
        "timeout": s.And(int, ensure_larger_than_zero),
        "max_concurrency": s.Or(s.And(int, ensure_larger_than_zero), None),
    },
    s.Optional("backlog"): s.And(int, ensure_larger_than(64)),
    s.Optional("max_runner_connections"): s.And(int, ensure_larger_than_zero),
    s.Optional("metrics"): {
        "enabled": bool,
        "namespace": str,
        s.Optional("duration"): {
            s.Optional("buckets", default=DEFAULT_BUCKET): s.Or(
                s.And(list, ensure_iterable_type(float)), None
            ),
            s.Optional("min"): s.Or(s.And(float, ensure_larger_than_zero), None),
            s.Optional("max"): s.Or(s.And(float, ensure_larger_than_zero), None),
            s.Optional("factor"): s.Or(s.And(float, ensure_larger_than(1.0)), None),
        },
    },
    s.Optional("logging"): {
        "access": {
            "enabled": bool,
            "request_content_length": s.Or(bool, None),
            "request_content_type": s.Or(bool, None),
            "response_content_length": s.Or(bool, None),
            "response_content_type": s.Or(bool, None),
            "format": {
                "trace_id": str,
                "span_id": str,
            },
        },
    },
    s.Optional("http"): {
        "host": s.And(str, is_valid_ip_address),
        "port": s.And(int, ensure_larger_than_zero),
        "cors": {
            "enabled": bool,
            "access_control_allow_origins": s.Or([str], str, None),
            "access_control_allow_origin_regex": s.Or(
                s.And(str, s.Use(re.compile)), None
            ),
            "access_control_allow_credentials": s.Or(bool, None),
            "access_control_allow_headers": s.Or([str], str, None),
            "access_control_allow_methods": s.Or([str], str, None),
            "access_control_max_age": s.Or(int, None),
            "access_control_expose_headers": s.Or([str], str, None),
        },
        "response": {"trace_id": bool},
    },
    s.Optional("grpc"): {
        "host": s.And(str, is_valid_ip_address),
        "port": s.And(int, ensure_larger_than_zero),
        "metrics": {
            "port": s.And(int, ensure_larger_than_zero),
            "host": s.And(str, is_valid_ip_address),
        },
        "reflection": {"enabled": bool},
        "channelz": {"enabled": bool},
        "max_concurrent_streams": s.Or(int, None),
        "max_message_length": s.Or(int, None),
        "maximum_concurrent_rpcs": s.Or(int, None),
    },
    s.Optional("ssl"): {
        "enabled": bool,
        s.Optional("certfile"): s.Or(str, None),
        s.Optional("keyfile"): s.Or(str, None),
        s.Optional("keyfile_password"): s.Or(str, None),
        s.Optional("version"): s.Or(s.And(int, ensure_larger_than_zero), None),
        s.Optional("cert_reqs"): s.Or(int, None),
        s.Optional("ca_certs"): s.Or(str, None),
        s.Optional("ciphers"): s.Or(str, None),
    },
    s.Optional("runner_probe"): {
        "enabled": bool,
        "timeout": int,
        "period": int,
    },
    s.Optional("monitoring"): {
        "enabled": bool,
        s.Optional("type"): s.Or(str, None),
        s.Optional("options"): s.Or(dict, None),
    },
    s.Optional("tracing"): TRACING_CFG,
}

SCHEMA = s.Schema(
    {
        s.Optional("version", default=2): s.And(int, lambda v: v == 2),
        "services": {
            **_SERVICE_CONFIG,
            s.Optional(str): _SERVICE_CONFIG,
        },
    }
)


def migration(*, default_config: dict[str, t.Any], override_config: dict[str, t.Any]):
    # We will use a flattened config to make it easier to migrate,
    # Then we will convert it back to a nested config.
    if depth(override_config) > 1:
        raise ValueError("'override_config' must be a flattened dictionary.") from None

    if "version" not in override_config:
        override_config["version"] = 2

    default_service_config = deepcopy(default_config["services"])
    for key in list(override_config):
        if key.startswith("services."):
            svc_name = key.split(".")[1]
            default_config["services"][svc_name] = default_service_config

    return unflatten(override_config)
