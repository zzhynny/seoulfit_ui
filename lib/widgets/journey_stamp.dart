import 'dart:async';

import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../theme/theme.dart';

/// The static illustration stamp.py uses as its images.edit base.
const kJourneyBackgroundAsset = 'assets/images/recap-railway-bg.png';

/// The app logo, pulsing over the card while the stamp is being painted.
const kAppLogoAsset = 'assets/icon/app_icon.png';

/// stamp.py asks for 1024x1536. The stamp's box takes exactly this shape so
/// the whole image shows, with nothing cropped.
const kStampAspectRatio = 1024 / 1536;

/// `$apiBase/static/stamps/{tripId}.png`, versioned so a regenerated stamp
/// (same path, new bytes) isn't served stale out of Flutter's image cache.
String stampImageUrl(String apiBase, String tripId, int version) =>
    '$apiBase/static/stamps/$tripId.png?v=$version';

/// The trip's journey stamp on the recap.
///
/// Until one is ready this shows [placeholder] (the native railway card), with
/// the pulsing app logo on top while the backend is still painting. Once ready
/// it hands the whole, uncropped image to [readyBuilder] to lay out.
///
/// Asks the backend (GET /trip/stamp) instead of guessing from failed image
/// loads, so "still painting" gets the loading logo while "none" and "failed"
/// just keep the placeholder. Polls every [pollEvery] while generating, at
/// most [maxPolls] times.
class JourneyStamp extends StatefulWidget {
  const JourneyStamp({
    super.key,
    required this.tripId,
    required this.placeholder,
    required this.readyBuilder,
    this.apiBase = '',
    this.pollEvery = const Duration(seconds: 3),
    this.maxPolls = 60,
    this.fetchStatus,
    this.onReady,
  });

  final String tripId;
  final Widget placeholder;
  final Widget Function(BuildContext context, Widget stamp) readyBuilder;
  final String apiBase;
  final Duration pollEvery;
  final int maxPolls;

  /// Defaults to [ApiService.fetchStampStatus]; injectable for tests.
  final Future<StampStatus> Function(String tripId)? fetchStatus;

  /// Called with the stamp's image link once it's ready — the recap uses it
  /// to offer Download.
  final ValueChanged<String>? onReady;

  @override
  State<JourneyStamp> createState() => _JourneyStampState();
}

class _JourneyStampState extends State<JourneyStamp> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 900));
  late final CurvedAnimation _curve = CurvedAnimation(parent: _pulse, curve: Curves.easeInOut);
  late final Animation<double> _scale = Tween<double>(begin: 0.9, end: 1.06).animate(_curve);

  StampStatus _status = (status: 'none', version: null);
  Timer? _next;
  int _polls = 0;

  bool get _generating => _status.status == 'generating';

  @override
  void initState() {
    super.initState();
    _poll();
  }

  @override
  void dispose() {
    _next?.cancel();
    _curve.dispose();
    _pulse.dispose();
    super.dispose();
  }

  Future<void> _poll() async {
    _polls++;
    StampStatus status;
    try {
      status = await (widget.fetchStatus ?? ApiService().fetchStampStatus)(widget.tripId);
    } catch (_) {
      status = (status: 'none', version: null);
    }
    if (!mounted) return;
    // A generation that outlives the cap is treated as not coming: the
    // placeholder is a better resting state than a logo that never stops.
    if (status.status == 'generating' && _polls >= widget.maxPolls) {
      status = (status: 'none', version: null);
    }
    setState(() => _status = status);
    final version = status.version;
    if (status.status == 'ready' && version != null) {
      widget.onReady?.call(stampImageUrl(widget.apiBase, widget.tripId, version));
    }
    if (_generating) {
      _pulse.repeat(reverse: true);
      _next = Timer(widget.pollEvery, _poll);
    } else {
      _pulse.stop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final version = _status.version;
    if (_status.status == 'ready' && version != null) {
      final plain = Image.asset(kJourneyBackgroundAsset, fit: BoxFit.cover);
      return widget.readyBuilder(
        context,
        AspectRatio(
          aspectRatio: kStampAspectRatio,
          child: Image.network(
            stampImageUrl(widget.apiBase, widget.tripId, version),
            fit: BoxFit.contain,
            frameBuilder: (context, child, frame, _) => frame == null ? plain : child,
            errorBuilder: (context, error, stackTrace) => plain,
          ),
        ),
      );
    }
    if (!_generating) return widget.placeholder;
    return Stack(
      children: [
        widget.placeholder,
        Positioned.fill(child: _loading(context)),
      ],
    );
  }

  Widget _loading(BuildContext context) {
    final logo = ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: Image.asset(kAppLogoAsset, width: 64, height: 64),
    );
    return ColoredBox(
      color: Colors.white.withValues(alpha: 0.6),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            MediaQuery.of(context).disableAnimations
                ? logo
                : ScaleTransition(scale: _scale, child: logo),
            const SizedBox(height: 12),
            Text(
              'Creating your stamp…',
              style: AppTextStyles.bodyMedium.copyWith(
                color: AppColors.primary,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
