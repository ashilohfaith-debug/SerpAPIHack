"""Everyday system abilities a blind user needs by voice: status (time, date,
battery, internet), volume, installed apps, windows, files/folders, web, arithmetic.

Each module is a thin, honest wrapper over a Windows facility. Anything that changes
the machine still goes through the executor's permission gate and the transparent
runner (announce -> act -> verify -> narrate)."""
