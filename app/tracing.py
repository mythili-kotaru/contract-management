import os
from contextlib import contextmanager
from langfuse import Langfuse
from langfuse.decorators import observe, langfuse_context

# Initialize Langfuse client
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

@contextmanager
def trace_node(name: str, **kwargs):
    """
    Context manager to create a span for a LangGraph node within the current trace.
    If no current trace exists in context, this will create a new one (though ideally
    it should be called within an @observe() wrapped function).
    """
    span = langfuse.span(
        name=name,
        **kwargs
    )
    try:
        yield span
    except Exception as e:
        span.update(level="ERROR", status_message=str(e))
        raise
    finally:
        span.end()
