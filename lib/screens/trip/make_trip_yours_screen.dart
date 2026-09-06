import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../models/trip.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/activity_card.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/primary_button.dart';
import 'swap_candidates_sheet.dart';

class MakeTripYoursScreen extends StatefulWidget {
  const MakeTripYoursScreen({super.key, required this.onOptimize, required this.onBack});

  final VoidCallback onOptimize;
  final VoidCallback onBack;

  @override
  State<MakeTripYoursScreen> createState() => _MakeTripYoursScreenState();
}

class _MakeTripYoursScreenState extends State<MakeTripYoursScreen> {
  String? _expandedId;

  Future<void> _pickReplacement(TripDay day, TripActivity activity) async {
    final replacement = await showSwapCandidatesSheet(
      context,
      day: day,
      activity: activity,
    );
    if (replacement == null || !mounted) return;
    // Recorded, not applied: the swap takes effect on the next Optimize,
    // which is the only call that re-runs the critic over the result.
    context.read<TripProvider>().swapActivity(activity.id, replacement);
  }

  @override
  Widget build(BuildContext context) {
    final trip = context.watch<TripProvider>();
    final itinerary = trip.itinerary!;
    final day = itinerary.days.firstWhere((d) => d.dayNumber == trip.selectedDay);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 24, 0),
          child: Row(
            children: [
              IconButton(onPressed: widget.onBack, icon: const Icon(Icons.chevron_left, size: 24)),
              Expanded(
                child: Text('Make This Trip Yours', style: AppTextStyles.headingSmall.copyWith(fontSize: 18)),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(color: AppColors.chipBackground, borderRadius: BorderRadius.circular(6)),
                child: Text(
                  'ADJUST PLAN',
                  style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: DayTabs(days: itinerary.days, selectedDay: trip.selectedDay, onSelect: trip.selectDay),
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 20, 16, 16),
            children: [
              for (final activity in day.activities) ...[
                GestureDetector(
                  onTap: () => setState(() => _expandedId = _expandedId == activity.id ? null : activity.id),
                  child: ToggleActivityCard(
                    activity: activity,
                    expanded: _expandedId == activity.id && activity.aiInsight != null,
                    onToggle: (v) => trip.toggleActivityIncluded(activity.id, v),
                  ),
                ),
                // Swapping is only meaningful for a stop that's staying in.
                if (activity.included)
                  _SwapRow(
                    pending: trip.pendingSwapFor(activity.id),
                    onSwap: () => _pickReplacement(day, activity),
                  ),
                const SizedBox(height: 12),
              ],
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: PrimaryButton(label: 'Optimize My Trip', onPressed: widget.onOptimize),
        ),
      ],
    );
  }
}

/// The swap affordance under a stop, and the record of one already chosen.
class _SwapRow extends StatelessWidget {
  const _SwapRow({required this.pending, required this.onSwap});

  /// Name of the replacement chosen but not yet applied, if any.
  final String? pending;
  final VoidCallback onSwap;

  @override
  Widget build(BuildContext context) {
    if (pending != null) {
      return Padding(
        padding: const EdgeInsets.only(top: 6, left: 4),
        child: Row(
          children: [
            const Icon(Icons.swap_horiz, size: 14, color: AppColors.primary),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                'Swapping for $pending',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTextStyles.caption.copyWith(
                  color: AppColors.primary,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            TextButton(
              onPressed: onSwap,
              child: Text('Change',
                  style: AppTextStyles.caption
                      .copyWith(color: AppColors.textSecondary)),
            ),
          ],
        ),
      );
    }

    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton.icon(
        onPressed: onSwap,
        icon: const Icon(Icons.swap_horiz, size: 16),
        label: const Text('Swap this stop'),
        style: TextButton.styleFrom(
          foregroundColor: AppColors.textSecondary,
          padding: const EdgeInsets.symmetric(horizontal: 4),
          minimumSize: const Size(0, 32),
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
          textStyle: AppTextStyles.bodySmall.copyWith(fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}
