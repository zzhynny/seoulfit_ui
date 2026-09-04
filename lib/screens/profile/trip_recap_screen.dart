import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../models/profile.dart';
import '../../models/trip.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

/// Minimum number of days with at least one check-in for the full
/// railway-map recap (17_Trip-Recap-Main) to show; below this, the
/// low-data variant (17-1_Trip-Recap-LowData) shows instead.
const kFullRecapStampThreshold = 2;

/// Fixed 5-stop railway layout, matching 17_Trip-Recap-Main's Figma design.
/// Used as fallback labels for any day beyond the actual mock trip length
/// (kept in the "not recorded" state) — per spec, 6+ day trips are out of
/// scope, so this list is never extended at runtime.
const _kFixedStopNames = ['Jongno', 'Bukchon', 'Namsan', 'Dongdaemun', 'Yeouido'];

/// A day's stamp state, thresholded on percent of activities visited —
/// matches Spec_Unrecorded-Day-Legend (86:246): 80%+ completed, 50-79%
/// partial, below that not recorded.
StampState _stateFor(TripDay day) {
  final total = day.activities.length;
  if (total == 0) return StampState.empty;
  final ratio = day.visitedCount / total;
  if (ratio >= 0.8) return StampState.visited;
  if (ratio >= 0.5) return StampState.partial;
  return StampState.empty;
}

class TripRecapScreen extends StatelessWidget {
  const TripRecapScreen({super.key, required this.onDone, required this.onBack});

  final VoidCallback onDone;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    final itinerary = context.watch<TripProvider>().itinerary;
    final days = itinerary?.days ?? const <TripDay>[];
    final stampedDays = itinerary?.stampedDays ?? 0;
    final fullRecap = stampedDays >= kFullRecapStampThreshold;

    return Column(
      children: [
        Container(
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border))),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          child: Row(
            children: [
              GestureDetector(onTap: onBack, child: const Icon(Icons.chevron_left, size: 20)),
              Expanded(
                child: Text('SeoulFit', textAlign: TextAlign.center, style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
              ),
              const SizedBox(width: 20),
            ],
          ),
        ),
        Expanded(
          child: fullRecap ? _FullRecapBody(days: days) : _LowDataRecapBody(days: days),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: PrimaryButton(label: 'Done', onPressed: onDone),
        ),
      ],
    );
  }
}

/// Derives a short display name + "Day N • X/Y Visited" (or "Planned")
/// label for a trip day, matching 17_Trip-Recap-Main's stop labels. Stamp
/// state is the same 80%/50% Spec_Unrecorded-Day-Legend thresholding used
/// by the low-data stamp-book grid, so the map's 3-state legend below
/// actually matches what's rendered on the track.
RecapStop _stopFor(TripDay day) {
  final name = day.areaName.replaceAll(' Area', '');
  final total = day.activities.length;
  final visited = day.visitedCount;
  final label = visited == 0
      ? 'Day ${day.dayNumber} • Planned'
      : visited == total
          ? 'Day ${day.dayNumber} • All Visited'
          : 'Day ${day.dayNumber} • $visited/$total Visited';
  return RecapStop(name: name, dayLabel: label, state: _stateFor(day));
}

/// Derives a stamp-book state ("Stamped" / "Started" / "Empty") for a trip
/// day, matching 17-1_Trip-Recap-LowData's stamp grid.
RecapStampDay _stampDayFor(TripDay day) {
  final state = _stateFor(day);
  final label = switch (state) {
    StampState.visited => 'Stamped',
    StampState.partial => 'Started',
    StampState.empty => 'Empty',
  };
  return RecapStampDay(dayNumber: day.dayNumber, state: state, label: label);
}

/// One stop's stamp + label position, each as its own independent center
/// fraction of the map-card's Figma bounding box — NOT derived from a
/// shared wrapper box. Pulled straight from Dev Mode MCP metadata for
/// frame 86:76 (17_Trip-Recap-Main), node "map-card" (105:4, 345x444):
/// the stamp ellipse's own top-left (not its label wrapper frame's
/// top-left, which is offset from the ellipse and was the source of the
/// earlier misalignment) plus half its 60x60 size gives its true center.
class _StopLayout {
  const _StopLayout({required this.stampCenter, required this.labelCenter});

  final Offset stampCenter;
  final Offset labelCenter;
}

class _FullRecapBody extends StatefulWidget {
  const _FullRecapBody({required this.days});

  final List<TripDay> days;

  @override
  State<_FullRecapBody> createState() => _FullRecapBodyState();
}

class _FullRecapBodyState extends State<_FullRecapBody> with SingleTickerProviderStateMixin {
  // map-card is 345x444 in Figma (the visible, clipped bounding box — its
  // cityscape-bg child bleeds 9px past the right edge and is cropped by
  // this frame, so 345 is the correct reference width, not 354).
  static const _cardAspectRatio = 345 / 444;

  static const _stopLayouts = [
    _StopLayout(stampCenter: Offset(170 / 345, 49 / 444), labelCenter: Offset(170 / 345, 100.5 / 444)), // 1) Jongno
    _StopLayout(stampCenter: Offset(52 / 345, 172 / 444), labelCenter: Offset(135.5 / 345, 172 / 444)), // 2) Bukchon
    _StopLayout(stampCenter: Offset(200 / 345, 273 / 444), labelCenter: Offset(285.5 / 345, 273 / 444)), // 3) Namsan
    _StopLayout(stampCenter: Offset(73 / 345, 335 / 444), labelCenter: Offset(153 / 345, 334 / 444)), // 4) Dongdaemun
    _StopLayout(stampCenter: Offset(259 / 345, 414 / 444), labelCenter: Offset(259 / 345, 367.5 / 444)), // 5) Yeouido
  ];

  // 70x70 per spec — FractionalTranslation's -0.5/-0.5 centering means this
  // expands symmetrically around the same track coordinate regardless of
  // size, so no re-anchoring is needed when this value changes.
  static const _stampSize = 70.0;

  static const _slamStep = 0.15;
  static const _slamSpan = 0.35;
  static const _slamDurationMs = 900;
  static const _initialDelayMs = 180;

  late final AnimationController _controller;
  late final List<Animation<double>> _slamAnims;
  // One player per stop so overlapping/staggered impacts don't cut each
  // other off — a single shared AudioPlayer would restart (and truncate)
  // on every play() call, which happens well before the previous stamp's
  // clip has finished given the ~135ms stagger step.
  late final List<AudioPlayer> _sfxPlayers;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(milliseconds: _slamDurationMs));
    _sfxPlayers = List.generate(_stopLayouts.length, (_) => AudioPlayer());
    _slamAnims = List.generate(_stopLayouts.length, (i) {
      final start = _slamStep * i;
      final end = (start + _slamSpan).clamp(0.0, 1.0);
      return Tween<double>(begin: 2.2, end: 1.0).animate(
        CurvedAnimation(parent: _controller, curve: Interval(start, end, curve: Curves.easeOutBack)),
      );
    });
    // Web-safe trigger: wait for the first real frame (so the map card has
    // actually been laid out), then a short extra delay before starting —
    // starting forward() inside initState/build itself can get dropped by
    // Flutter Web's first paint.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      Future.delayed(const Duration(milliseconds: _initialDelayMs), () {
        if (!mounted) return;
        _controller.forward(from: 0.0);
        for (var i = 0; i < _stopLayouts.length; i++) {
          final end = (_slamStep * i + _slamSpan).clamp(0.0, 1.0);
          final impactMs = (end * _slamDurationMs).round();
          Future.delayed(Duration(milliseconds: impactMs), () => _playImpactSfx(i));
        }
      });
    });
  }

  Future<void> _playImpactSfx(int index) async {
    if (!mounted) return;
    try {
      // Fire-and-forget: never awaited by the animation itself, so a slow
      // or blocked decode can't stall the UI thread or delay the next
      // stamp's slam.
      await _sfxPlayers[index].play(AssetSource('cute-peta-stamp.mp3'));
    } catch (_) {
      // Browsers can block audio autoplay until the user has interacted
      // with the page at least once — swallow that rather than let a
      // sound-effect failure break the recap screen.
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    for (final player in _sfxPlayers) {
      player.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // Fixed 5-node railway regardless of actual trip length — a mock trip
    // shorter than 5 days only stamps the days it actually has; the
    // remaining nodes stay in the "not recorded" dashed state.
    final stops = List.generate(_stopLayouts.length, (i) {
      if (i < widget.days.length) return _stopFor(widget.days[i]);
      return RecapStop(
        name: _kFixedStopNames[i],
        dayLabel: 'Day ${i + 1} • Not Recorded',
        state: StampState.empty,
      );
    });

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Your Trip Recap', style: AppTextStyles.headingMedium.copyWith(fontSize: 26)),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: AspectRatio(
              aspectRatio: _cardAspectRatio,
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF8F0),
                  border: Border.all(color: AppColors.border),
                  borderRadius: BorderRadius.circular(16),
                ),
                // The background illustration and the stamp overlays are
                // direct siblings of this SAME Stack, which is itself the
                // AspectRatio's only child — so both share exactly one
                // locked-size box; LayoutBuilder below reads that box's
                // real pixel size on every layout pass (not a separately
                // estimated one), so the ratios stay locked to the track
                // regardless of viewport size.
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final w = constraints.maxWidth;
                    final h = constraints.maxHeight;
                    return Stack(
                      clipBehavior: Clip.none,
                      children: [
                        Positioned.fill(
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(16),
                            child: Image.asset('assets/images/recap-railway-bg.png', fit: BoxFit.cover),
                          ),
                        ),
                        Positioned(
                          left: 24,
                          top: 10,
                          child: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                            decoration: BoxDecoration(
                              color: Colors.white.withValues(alpha: 0.85),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              'YOUR SEOUL JOURNEY',
                              style: AppTextStyles.caption.copyWith(color: const Color(0xFF5E836A), fontWeight: FontWeight.w600),
                            ),
                          ),
                        ),
                        for (var i = 0; i < stops.length; i++) ...[
                          Positioned(
                            left: w * _stopLayouts[i].stampCenter.dx,
                            top: h * _stopLayouts[i].stampCenter.dy,
                            child: FractionalTranslation(
                              // Centers the stamp exactly on the target
                              // point regardless of the child's own size —
                              // no separate radius bookkeeping needed. The
                              // slam scale below grows/shrinks from this
                              // same center, so it never shifts the anchor.
                              translation: const Offset(-0.5, -0.5),
                              child: AnimatedBuilder(
                                animation: _slamAnims[i],
                                builder: (context, child) => Transform.scale(scale: _slamAnims[i].value, child: child),
                                child: Image.asset(
                                  switch (stops[i].state) {
                                    StampState.visited => 'assets/images/stamp-paw-green.png',
                                    StampState.partial => 'assets/images/stamp-paw-partial.png',
                                    StampState.empty => 'assets/images/stamp-paw-empty.png',
                                  },
                                  width: _stampSize,
                                  height: _stampSize,
                                  fit: BoxFit.contain,
                                ),
                              ),
                            ),
                          ),
                          Positioned(
                            left: w * _stopLayouts[i].labelCenter.dx,
                            top: h * _stopLayouts[i].labelCenter.dy,
                            child: FractionalTranslation(
                              translation: const Offset(-0.5, -0.5),
                              child: _StopLabel(stop: stops[i]),
                            ),
                          ),
                        ],
                      ],
                    );
                  },
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _legendItem(_solidDot(AppColors.primary), 'Completed'),
                const SizedBox(width: 12),
                _legendItem(_solidDot(AppColors.primary.withValues(alpha: 0.35)), 'Partial'),
                const SizedBox(width: 12),
                _legendItem(_dashedDot(), 'Planned'),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Center(
            child: Text(
              'Thanks for exploring Seoul with SeoulFit!',
              textAlign: TextAlign.center,
              style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary, fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }

  Widget _legendItem(Widget dot, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        dot,
        const SizedBox(width: 5),
        Text(label, style: AppTextStyles.caption),
      ],
    );
  }

  Widget _solidDot(Color color) {
    return Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
  }

  Widget _dashedDot() {
    return const SizedBox(width: 10, height: 10, child: CustomPaint(painter: _DashedCirclePainter()));
  }
}

/// A small dashed-outline circle for the "Planned" (not recorded) legend
/// swatch — matches Spec_Unrecorded-Day-Legend's neutral gray dashed paw
/// outline treatment, scaled down to a plain dot for the legend row.
class _DashedCirclePainter extends CustomPainter {
  const _DashedCirclePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFF9CA3AF)
      ..strokeWidth = 1.2
      ..style = PaintingStyle.stroke;
    final radius = size.width / 2;
    final center = Offset(radius, radius);
    const dashCount = 8;
    const dashDegrees = 360 / dashCount * 0.6;
    for (var i = 0; i < dashCount; i++) {
      final startAngle = (360 / dashCount * i) * (3.1415926535 / 180);
      final sweepAngle = dashDegrees * (3.1415926535 / 180);
      canvas.drawArc(Rect.fromCircle(center: center, radius: radius - 0.6), startAngle, sweepAngle, false, paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _StopLabel extends StatelessWidget {
  const _StopLabel({required this.stop});

  final RecapStop stop;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.85),
        border: Border.all(color: const Color(0xFF5E836A).withValues(alpha: 0.2)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(stop.name, style: AppTextStyles.caption.copyWith(fontWeight: FontWeight.w700, color: const Color(0xFF2D2A26))),
          Text(stop.dayLabel, style: AppTextStyles.caption.copyWith(fontSize: 9, color: const Color(0xFF5E836A))),
        ],
      ),
    );
  }
}

class _LowDataRecapBody extends StatelessWidget {
  const _LowDataRecapBody({required this.days});

  final List<TripDay> days;

  @override
  Widget build(BuildContext context) {
    final stampDays = days.map(_stampDayFor).toList();
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Your Trip Recap', style: AppTextStyles.headingMedium.copyWith(fontSize: 28)),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFFFFF8F0),
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('YOUR STAMP BOOK', style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600)),
                const SizedBox(height: 14),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    for (final day in stampDays) _stampCell(day),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFFFFF8F0),
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              "We didn't get enough check-ins to calculate your completion stats this trip - but here's what you collected!",
              style: AppTextStyles.bodySmall.copyWith(height: 1.6),
            ),
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            decoration: BoxDecoration(
              color: const Color(0xFFFFF8F0),
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Container(width: 3, height: 70, color: AppColors.primary),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 14, 14, 14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.auto_awesome, size: 14, color: AppColors.textPrimary),
                            const SizedBox(width: 6),
                            Text('Next Time in Seoul', style: AppTextStyles.bodyMedium.copyWith(fontWeight: FontWeight.w700)),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Enable check-ins from the start to unlock your full stamp collection and trip completion stats!',
                          style: AppTextStyles.caption.copyWith(height: 1.5),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _stampCell(RecapStampDay day) {
    final asset = switch (day.state) {
      StampState.visited => 'assets/images/stamp-paw-green.png',
      StampState.partial => 'assets/images/stamp-paw-partial.png',
      StampState.empty => 'assets/images/stamp-paw-empty.png',
    };
    final labelColor = switch (day.state) {
      StampState.visited => AppColors.primary,
      StampState.partial => AppColors.primary,
      StampState.empty => const Color(0xFF9CA3AF),
    };
    return Column(
      children: [
        Image.asset(asset, width: 60, height: 60, fit: BoxFit.contain),
        const SizedBox(height: 6),
        Text('Day ${day.dayNumber}', style: AppTextStyles.caption.copyWith(fontWeight: FontWeight.w700)),
        Text(day.label, style: AppTextStyles.caption.copyWith(fontSize: 9, color: labelColor)),
      ],
    );
  }
}
