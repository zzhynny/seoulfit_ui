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
  return RecapStop(name: name, dayLabel: label, visited: visited > 0);
}

/// Derives a stamp-book state ("Stamped" / "Started" / "Empty") for a trip
/// day, matching 17-1_Trip-Recap-LowData's stamp grid.
RecapStampDay _stampDayFor(TripDay day) {
  final total = day.activities.length;
  final visited = day.visitedCount;
  final state = visited == 0
      ? StampState.empty
      : visited == total
          ? StampState.visited
          : StampState.partial;
  final label = switch (state) {
    StampState.visited => 'Stamped',
    StampState.partial => 'Started',
    StampState.empty => 'Empty',
  };
  return RecapStampDay(dayNumber: day.dayNumber, state: state, label: label);
}

class _FullRecapBody extends StatelessWidget {
  const _FullRecapBody({required this.days});

  final List<TripDay> days;

  /// Exact top-left offsets of each stamp, as fractions of the map card's
  /// Figma bounding box (354x444), taken directly from the 17_Trip-Recap-Main
  /// frame's node coordinates via Dev Mode MCP:
  ///  1) left:120 top:18   2) left:21  top:141  3) left:169 top:242
  ///  4) left:42  top:304  5) left:228 top:383
  static const _cardAspectRatio = 354 / 444;
  static const _stampOffsets = [
    Offset(120 / 354, 18 / 444),
    Offset(21 / 354, 141 / 444),
    Offset(169 / 354, 242 / 444),
    Offset(42 / 354, 304 / 444),
    Offset(228 / 354, 383 / 444),
  ];
  static const _stampSize = 38.0;

  @override
  Widget build(BuildContext context) {
    final stops = days.map(_stopFor).toList();
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
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final w = constraints.maxWidth;
                    final h = constraints.maxHeight;
                    return Stack(
                      // Labels are allowed to sit slightly outside a stop's
                      // own anchor box (e.g. above the stamp for the last
                      // stop, see labelAbove below) — never hard-clip them.
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
                        for (var i = 0; i < stops.length && i < _stampOffsets.length; i++)
                          Positioned(
                            left: _stampOffsets[i].dx * w,
                            top: _stampOffsets[i].dy * h,
                            // The last stop sits close to the card's bottom
                            // edge — its label renders above the stamp
                            // instead of below so it can't get clipped.
                            child: _RecapStopMarker(
                              stop: stops[i],
                              stampSize: _stampSize,
                              labelAbove: i == _stampOffsets.length - 1,
                            ),
                          ),
                      ],
                    );
                  },
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              _legendDot(AppColors.primary, 'Visited'),
              const SizedBox(width: 16),
              _legendDot(AppColors.border, 'Planned'),
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

  Widget _legendDot(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 5),
        Text(label, style: AppTextStyles.caption),
      ],
    );
  }
}

class _RecapStopMarker extends StatelessWidget {
  const _RecapStopMarker({required this.stop, required this.stampSize, this.labelAbove = false});

  final RecapStop stop;
  final double stampSize;
  final bool labelAbove;

  @override
  Widget build(BuildContext context) {
    final stamp = Image.asset(
      stop.visited ? 'assets/images/stamp-paw-green.png' : 'assets/images/stamp-paw-empty.png',
      width: stampSize,
      height: stampSize,
      fit: BoxFit.contain,
    );
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
    return Column(
      mainAxisSize: MainAxisSize.min,
      // start (not center): the stamp's own top-left is the exact Figma
      // anchor point — a wider label must not re-center the stamp.
      crossAxisAlignment: CrossAxisAlignment.start,
      children: labelAbove
          ? [label, const SizedBox(height: 4), stamp]
          : [stamp, const SizedBox(height: 4), label],
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
