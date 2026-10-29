# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The AI assistant and the MCP bridge (docs/ai.md).

Off by default. ``tools`` is the one catalogue both of them use: every
tool runs on the drawing through the same Commands as the keyboard, so
whatever an AI does is undoable -- one turn, one undo step.
"""
