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
/// label for a trip day, matching 17_Trip-Recap-Main's stop labels.
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

class _FullRecapBody extends StatefulWidget {
  const _FullRecapBody({required this.days});

  final List<TripDay> days;

  @override
  State<_FullRecapBody> createState() => _FullRecapBodyState();
}

class _FullRecapBodyState extends State<_FullRecapBody> with SingleTickerProviderStateMixin {
  static const _cardAspectRatio = 354 / 444;

  // Each stop's stamp-CENTER position as a fraction of the 354x444 Figma
  // card, converted to Alignment's -1..1 range (x = 2*fracX-1). Anchoring
  // via Align (not Positioned+pixel offsets, which broke on viewport-size
  // changes) keeps every stop locked to the railway track regardless of
  // screen size, since Align re-resolves against the AspectRatio-locked
  // card's actual size on every layout pass.
  static const _stampAlignments = [
    Alignment(-0.2147, -0.8333), // 1) Jongno
    Alignment(-0.7740, -0.2793), // 2) Bukchon
    Alignment(0.0621, 0.1757), // 3) Namsan
    Alignment(-0.6554, 0.4550), // 4) Dongdaemun
    Alignment(0.3955, 0.8108), // 5) Yeouido (Day 5 — label renders above so it can't clip)
  ];

  static const _staggerStepMs = 90;
  static const _slamMs = 420;

  late final AnimationController _controller;
  late final List<Animation<double>> _scaleAnims;
  late final List<Animation<double>> _rotateAnims;

  @override
  void initState() {
    super.initState();
    final totalMs = _staggerStepMs * (_stampAlignments.length - 1) + _slamMs;
    _controller = AnimationController(vsync: this, duration: Duration(milliseconds: totalMs));
    _scaleAnims = [];
    _rotateAnims = [];
    for (var i = 0; i < _stampAlignments.length; i++) {
      final start = (_staggerStepMs * i) / totalMs;
      final end = (_staggerStepMs * i + _slamMs) / totalMs;
      final interval = Interval(start, end, curve: Curves.elasticOut);
      _scaleAnims.add(Tween<double>(begin: 1.6, end: 1.0).animate(CurvedAnimation(parent: _controller, curve: interval)));
      _rotateAnims.add(Tween<double>(begin: -0.12, end: 0.0).animate(CurvedAnimation(parent: _controller, curve: interval)));
    }
    _controller.forward();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // Fixed 5-node railway regardless of actual trip length — a mock trip
    // shorter than 5 days only stamps the days it actually has; the
    // remaining nodes stay in the "not recorded" dashed state.
    final stops = List.generate(_stampAlignments.length, (i) {
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
                // locked-size box; nothing here separately estimates the
                // image's bounds.
                child: Stack(
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
                    for (var i = 0; i < stops.length; i++)
                      Align(
                        alignment: _stampAlignments[i],
                        child: _RecapStopMarker(
                          stop: stops[i],
                          scale: _scaleAnims[i],
                          rotate: _rotateAnims[i],
                          labelAbove: i == stops.length - 1,
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              _legendDot('assets/images/stamp-paw-green.png', 'Completed'),
              const SizedBox(width: 14),
              _legendDot('assets/images/stamp-paw-partial.png', 'Partial'),
              const SizedBox(width: 14),
              _legendDot('assets/images/stamp-paw-empty.png', 'Not Recorded'),
            ],
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

  Widget _legendDot(String asset, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Image.asset(asset, width: 16, height: 16, fit: BoxFit.contain),
        const SizedBox(width: 5),
        Text(label, style: AppTextStyles.caption),
      ],
    );
  }
}

class _RecapStopMarker extends StatelessWidget {
  const _RecapStopMarker({
    required this.stop,
    required this.scale,
    required this.rotate,
    this.labelAbove = false,
  });

  final RecapStop stop;
  final Animation<double> scale;
  final Animation<double> rotate;
  final bool labelAbove;

  // Kept tight and symmetric around the stamp itself (not the wider label)
  // so Align's own child-size math stays anchored on the stamp's true
  // center — the label is allowed to overflow this box via the parent
  // Stack's Clip.none instead of widening it.
  static const _boxSize = 44.0;
  static const _stampSize = 38.0;

  @override
  Widget build(BuildContext context) {
    final asset = switch (stop.state) {
      StampState.visited => 'assets/images/stamp-paw-green.png',
      StampState.partial => 'assets/images/stamp-paw-partial.png',
      StampState.empty => 'assets/images/stamp-paw-empty.png',
    };
    final stampImage = Image.asset(asset, width: _stampSize, height: _stampSize, fit: BoxFit.contain);
    final label = Container(
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

    return SizedBox(
      width: _boxSize,
      height: _boxSize,
      child: Stack(
        clipBehavior: Clip.none,
        alignment: Alignment.center,
        children: [
          AnimatedBuilder(
            animation: scale,
            builder: (context, child) => Transform.rotate(
              angle: rotate.value,
              child: Transform.scale(scale: scale.value, child: child),
            ),
            child: stampImage,
          ),
          Positioned(
            left: -80,
            right: -80,
            top: labelAbove ? null : _boxSize + 4,
            bottom: labelAbove ? _boxSize + 4 : null,
            child: Center(child: label),
          ),
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
