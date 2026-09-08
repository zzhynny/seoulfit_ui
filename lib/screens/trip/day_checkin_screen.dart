import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/activity_card.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/primary_button.dart';

class DayCheckInScreen extends StatelessWidget {
  const DayCheckInScreen({
    super.key,
    required this.dayNumber,
    required this.onComplete,
    required this.onMissedPlace,
    required this.onBack,
    required this.onSelectDay,
  });

  final int dayNumber;
  final VoidCallback onComplete;
  final void Function(String activityId) onMissedPlace;
  final VoidCallback onBack;

  /// Tapping a day tab. The screen reads its day from the route, so switching
  /// days is the router's call -- it hands back a screen for the new day
  /// rather than this one mutating [dayNumber] it does not own.
  final ValueChanged<int> onSelectDay;

  @override
  Widget build(BuildContext context) {
    final trip = context.watch<TripProvider>();
    final companion = context.watch<CompanionProvider>().selected;
    final itinerary = trip.itinerary!;
    final day = itinerary.days.firstWhere((d) => d.dayNumber == dayNumber);
    final stampedDays = itinerary.stampedDays;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 16, 24, 0),
          child: Row(
            children: [
              IconButton(
                onPressed: onBack,
                icon: const Icon(Icons.chevron_left, size: 28),
                color: AppColors.textPrimary,
                tooltip: 'Back',
              ),
              // The stamped-days chip used to sit in this row, unconstrained,
              // which left the 24pt title barely 90px to live in. Title first
              // across the full width, chip on the line below with the date.
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 30,
                          height: 30,
                          clipBehavior: Clip.antiAlias,
                          decoration: const BoxDecoration(shape: BoxShape.circle),
                          child: Image.asset(companion.portraitAsset, fit: BoxFit.contain),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Day $dayNumber Check-in',
                            style: AppTextStyles.headingMedium.copyWith(fontSize: 24),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${day.date} • ${day.areaName}',
                            style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                          decoration: BoxDecoration(color: AppColors.chipBackground, borderRadius: BorderRadius.circular(20)),
                          child: Text(
                            '$stampedDays/${itinerary.days.length} Days Stamped',
                            style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: DayTabs(days: itinerary.days, selectedDay: dayNumber, onSelect: onSelectDay),
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              for (final activity in day.activities) ...[
                CheckInActivityCard(
                  activity: activity,
                  onToggleVisited: () =>
                      trip.setVisited(activity.id, !activity.visited),
                  onMissed: () => onMissedPlace(activity.id),
                ),
                const SizedBox(height: 12),
              ],
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  border: Border.all(color: AppColors.border),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 48,
                      height: 48,
                      decoration: const BoxDecoration(color: AppColors.border, shape: BoxShape.circle),
                      alignment: Alignment.center,
                      child: const Icon(Icons.lock_outline, color: AppColors.textSecondary),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('${day.areaName} Stamps', style: AppTextStyles.headingSmall.copyWith(fontSize: 14, color: const Color(0xFF8A8A93))),
                          Text(
                            'Stamps activate when all places are visited (${day.visitedCount}/${day.activities.length})',
                            style: AppTextStyles.bodySmall,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: PrimaryButton(label: 'Complete Check-in', onPressed: onComplete),
        ),
      ],
    );
  }
}
