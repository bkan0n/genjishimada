# Formattables & Pretty Printing

This section covers how to format model data into readable, consistent strings for embeds and messages.

## Formattable models

A formattable model implements `to_format_dict()` and returns a mapping of display labels to string values.
The formatter uses this mapping to build a nicely aligned, readable block for Discord.

The interface lives in `apps/bot/utilities/formatter.py`:

```python
class FormattableProtocol(Protocol):
    def to_format_dict(self) -> dict[str, str | None]:
        ...
```

## Formatter classes

Two formatters are available in `apps/bot/utilities/formatter.py`:

- `Formatter` - draws a tree-like list with `┣`/`┗` prefix characters.
- `FilteredFormatter` - renders blockquote-style lines and lets you exclude fields.

Both drop keys whose values are `None`, `False`, or empty strings.

## Example: format a completion payload

`CompletionSubmissionModel` implements `to_format_dict()` in `apps/bot/utilities/completions.py`.

```python
from utilities.completions import CompletionSubmissionModel
from utilities.formatter import Formatter

model = CompletionSubmissionModel(**payload)
formatted = Formatter(model).format()

# Use in an embed description or message body
embed.description = formatted
```

## Example: filter fields

Use `FilteredFormatter` when you want a smaller summary:

```python
from utilities.maps import MapModel
from utilities.formatter import FilteredFormatter

model = MapModel(**payload)
formatted = FilteredFormatter(
    model,
    filter_fields={"Mechanics", "Restrictions"},
).format()
```

## Implementing a new formattable

Wrap SDK models or view models in a small class that implements `to_format_dict()`.

```python
class MyFormattable:
    def __init__(self, name: str, score: int) -> None:
        self.name = name
        self.score = score

    def to_format_dict(self) -> dict[str, str | None]:
        return {
            "Name": self.name,
            "Score": str(self.score),
        }
```

## Tips

- Keep keys short and consistent (`Code`, `Map`, `Time`).
- Return `""` for optional fields you want hidden.
- Use inline Markdown sparingly (e.g., `"[Link](...)"`).

## Next Steps

- [Services & Extensions](../architecture/services.md) - Understand service architecture
- [Messaging & Queues](../architecture/messaging.md) - Learn about queue events
- [SDK Documentation](../../sdk/index.md) - See payload models
