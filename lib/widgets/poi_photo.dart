import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_service.dart';
import 'placeholder_photo.dart';

/// A place photo resolved lazily from the backend's `/poi-image`.
///
/// The itinerary payload carries no images — a photo costs a SerpApi lookup
/// plus a Gemini pick per stop, so resolving all of them up front would put
/// dozens of round-trips in front of the itinerary appearing. Each card
/// fetches its own on first build instead; [ApiService] memoises by name, so
/// scrolling back to a card it has already seen costs nothing.
///
/// [asset] short-circuits the whole thing, which is what keeps the mock build
/// on its bundled Figma artwork and off the network.
class PoiPhoto extends StatefulWidget {
  const PoiPhoto({
    super.key,
    required this.name,
    this.type = '',
    this.asset,
    this.size,
    this.borderRadius = 12,
  });

  final String name;

  /// The planner's raw `poi_type`. /poi-image ranks candidates with it, and
  /// a bare Seoul name without it pulls back whatever matches the words.
  final String type;
  final String? asset;
  final double? size;
  final double borderRadius;

  @override
  State<PoiPhoto> createState() => _PoiPhotoState();
}

class _PoiPhotoState extends State<PoiPhoto> {
  String? _url;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(PoiPhoto oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Lists reuse this State by position, so switching day tabs hands it a
    // different stop — without this it keeps showing the previous stop's photo.
    if (oldWidget.name != widget.name) _load();
  }

  void _load() {
    _url = null;
    if (widget.asset != null || widget.name.isEmpty) return;
    // Same as PoiSummary: a photo this session already resolved paints on the
    // first frame, instead of a placeholder that swaps on every screen.
    final saved = context.read<ApiService?>()?.cachedPoiImage(widget.name);
    if (saved != null) {
      if (saved.isNotEmpty) _url = saved;
      return;
    }
    _resolve();
  }

  Future<void> _resolve() async {
    // Absent in the mock build, where no ApiService is provided.
    final api = context.read<ApiService?>();
    if (api == null) return;

    final name = widget.name;
    try {
      final url = await api.fetchPoiImage(name, type: widget.type);
      if (mounted && name == widget.name && url.isNotEmpty) setState(() => _url = url);
    } catch (_) {
      // A missing photo is not worth surfacing — the placeholder is the
      // designed empty state, and the card's text carries the meaning.
    }
  }

  @override
  Widget build(BuildContext context) {
    return PlaceholderPhoto(
      size: widget.size,
      borderRadius: widget.borderRadius,
      asset: widget.asset,
      url: _url,
    );
  }
}
