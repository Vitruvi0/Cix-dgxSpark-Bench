# Patched vLLM image plus the tool_choice "none" fix in the parser engine.
# No network access: the base is a local image built by ../build-base-image.sh.
# Build: DOCKER_BUILDKIT=1 docker build --network none -t flashnext-vllm:blazux-ad8920d-tcnone .
FROM flashnext-vllm:blazux-ad8920d
COPY patch_tool_choice_none.py /opt/llm/patch_tool_choice_none.py
RUN python3 /opt/llm/patch_tool_choice_none.py on
LABEL patch.toolchoice="none-without-tools" base="flashnext-vllm:blazux-ad8920d"
