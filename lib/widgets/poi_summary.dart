import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_service.dart';
import '../theme/theme.dart';

/// A place's own one-or-two sentence description, from `/poi-summary`.
///
/// Resolved per card rather than with the itinerary: each one is a Gemini
/// call, and a fourteen-stop plan would wait on fourteen of them before
/// showing anything. [ApiService] memoises by name, so scrolling back is
/// free.
///
/// [fallback] is the planner's own note for the stop — why it is in the plan,
/// as opposed to what the place is. It shows immediately and stays if the
/// lookup fails, so the line is never empty and never a spinner.
class PoiSummary extends StatefulWidget {
  const PoiSummary({
    super.key,
    required this.name,
    required this.fallback,
    this.type = '',
    this.maxLines = 2,
    this.style,
  });

  final String name;
  final String fallback;
  final String type;
  final int maxLines;
  final TextStyle? style;

  @override
  State<PoiSummary> createState() => _PoiSummaryState();
}

class _PoiSummaryState extends State<PoiSummary> {
  String? _summary;

  @override
  void initState() {
    super.initState();
    if (widget.name.isNotEmpty) _resolve();
  }

  Future<void> _resolve() async {
    // Null in the mock build, which has no backend to ask.
    final api = context.read<ApiService?>();
    if (api == null) return;

    try {
      final summary = await api.fetchPoiSummary(widget.name, type: widget.type);
      if (mounted && summary.trim().isNotEmpty) {
        setState(() => _summary = summary.trim());
      }
    } catch (_) {
      // The fallback is already on screen and reads as a real description,
      // so a failed lookup needs no error state.
    }
  }

  @override
  Widget build(BuildContext context) {
    return Text(
      _summary ?? widget.fallback,
      maxLines: widget.maxLines,
      overflow: TextOverflow.ellipsis,
      style: widget.style ?? AppTextStyles.bodySmall,
    );
  }
}
