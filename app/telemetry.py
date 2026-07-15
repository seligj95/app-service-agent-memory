from __future__ import annotations

import logging
import os
from functools import lru_cache

from azure.monitor.opentelemetry import configure_azure_monitor

LOGGER_NAME = "agent_memory"


@lru_cache
def configure_telemetry() -> logging.Logger:
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        configure_azure_monitor(
            logger_name=LOGGER_NAME,
            enable_live_metrics=True,
        )
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    return logger
