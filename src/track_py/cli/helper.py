import inspect


# Helper to handle both sync and async command functions
async def handle_coroutine_command(func, *args) -> str:
    isCoroutine = inspect.iscoroutinefunction(func)
    # need args
    if check_parameters(func):
        if isCoroutine:
            return await func(*args)
        else:
            return func(*args)
    else:
        if isCoroutine:
            return await func()
        else:
            return func()


# Check if function requires parameters
def check_parameters(func: callable) -> bool:
    sig = inspect.signature(func)
    return len(sig.parameters) > 0


# Extract offset from command string
def get_offset_from_command(command: str) -> int:
    parts = command.split()
    offset = 0
    if len(parts) > 1:
        try:
            offset = int(parts[1])
        except ValueError:
            print("Invalid offset value. Using default offset 0.")
    return offset
