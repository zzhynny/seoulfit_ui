import 'package:flutter/foundation.dart'
    show kIsWeb, defaultTargetPlatform, TargetPlatform;

/// Single source of truth for the FastAPI backend base URL.
///
/// - `--dart-define=API_BASE_URL=...` wins when provided (empty → same-origin).
/// - Otherwise a platform-aware local dev default: Android emulator reaches the
///   host via `10.0.2.2`, iOS simulator / desktop / web use `localhost`.
String get apiBase {
  final raw = _raw;
  if (raw.isEmpty) return '';
  return raw.endsWith('/') ? raw.substring(0, raw.length - 1) : raw;
}

String get _raw {
  if (const bool.hasEnvironment('API_BASE_URL')) {
    return const String.fromEnvironment('API_BASE_URL');
  }
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    return 'http://10.0.2.2:8000';
  }
  return 'http://localhost:8000';
}
