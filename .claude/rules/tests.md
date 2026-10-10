---
paths:
  - "**/test_*.py"
---
# Test rules
- When a test expects an error from our own validator, use pytest.raises(ValidationError, match="<our exact message>"). Don't match Pydantic's built-in messages (except "Extra inputs are not permitted").
- Avoid hardcoding paths; use tmp_path or tmp_path_factory for temporary directories.
- Use literal expected values rather than values calculated from the code's output, to ensure tests are deterministic and easy to understand.
- A happy-path test only builds the object or calls the function; never wrap it in pytest.raises.