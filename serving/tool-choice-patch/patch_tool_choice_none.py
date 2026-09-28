#!/usr/bin/env python3
"""Build-time patch of vLLM: tool_choice="none" suppresses tool calls even without tools.

A request without tools has tool_choice="none" by default, but ParserEngine
suppressed tool calls only when tools were present: in streaming, tool-call
markup generated spontaneously by the model became tool_calls with
finish_reason="tool_calls". The non-streaming path of serving.py already
ignores tool calls with tool_choice "none"; this aligns the streaming path.
With "off" the original file is restored byte for byte.
"""
import ast
import hashlib
import sys
from pathlib import Path

TARGET = Path(sys.argv[2] if len(sys.argv) > 2 else
              '/usr/local/lib/python3.12/dist-packages/vllm/parser/engine/parser_engine.py')
ORIGINAL_SHA = 'f837bd5ae7bf759732a7d829209f93444b5692746d981509630c9bd3fcb39edb'
BEFORE = '            if tool_choice == "none" and tools:\n'
AFTER = '            if tool_choice == "none":\n'


def main(mode):
    text = TARGET.read_text()
    backup = TARGET.with_suffix('.py.orig-toolchoice')
    if mode == 'off':
        if backup.exists():
            TARGET.write_bytes(backup.read_bytes())
        return
    # Only on the reviewed file: a different vLLM must be read again, not patched blindly.
    if hashlib.sha256(text.encode()).hexdigest() != ORIGINAL_SHA:
        raise SystemExit('parser_engine.py differs from the reviewed one')
    if text.count(BEFORE) != 1:
        raise SystemExit('anchor is not unique')
    patched = text.replace(BEFORE, AFTER)
    ast.parse(patched)
    backup.write_text(text)
    TARGET.write_text(patched)
    print('TOOLCHOICE-NONE patch active')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'on')
