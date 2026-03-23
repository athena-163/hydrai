---
name: image-understand
description: Analyze a local image or video path through the configured vision endpoint.
---

Use this skill when you need direct media understanding on a local path.

Prefer session attachment summaries first when they already answer the question.
Use this function when you need a targeted prompt or the attachment has not been summarized yet.

## Function

### `image_understand`
Schema:
```json
{
  "path": "string",
  "prompt": "string (optional, default 'Describe the media.')"
}
```

Notes:
- path must be absolute
- path policy may block protected roots
