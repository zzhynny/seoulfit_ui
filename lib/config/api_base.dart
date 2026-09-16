import 'package:flutter/foundation.dart'
    show kIsWeb, kReleaseMode, defaultTargetPlatform, TargetPlatform;

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
  // A released web build must never fall back to localhost: the browser would
  // resolve it against the *visitor's* machine, so every request goes to a
  // backend only they could be running, and the app looks broken for reasons
  // they cannot see. Same-origin is the sane default — it is correct when the
  // API is served from the same host, and when it is not, the failure at least
  // points at our own deployment. Pass --dart-define=API_BASE_URL for a
  // separate API host.
  if (kIsWeb && kReleaseMode) return '';
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    return 'http://10.0.2.2:8000';
  }
  return 'http://localhost:8000';
}
