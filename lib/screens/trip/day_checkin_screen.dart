import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
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
  });

  final int dayNumber;
  final VoidCallback onComplete;
  final void Function(String activityId) onMissedPlace;

  @override
  Widget build(BuildContext context) {
    final trip = context.watch<TripProvider>();
    final itinerary = trip.itinerary!;
    final day = itinerary.days.firstWhere((d) => d.dayNumber == dayNumber);
    final stampedDays = itinerary.stampedDays;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Image.asset(
                          'assets/images/stamp-paw-green.png',
                          width: 30,
                          height: 30,
                          fit: BoxFit.contain,
                        ),
                        const SizedBox(width: 8),
                        Text('Day $dayNumber Check-in', style: AppTextStyles.headingMedium.copyWith(fontSize: 24)),
                      ],
                    ),
                    Text('${day.date} • ${day.areaName}', style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary)),
                  ],
                ),
              ),
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
        ),
        const SizedBox(height: 16),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: DayTabs(days: itinerary.days, selectedDay: dayNumber, onSelect: (_) {}),
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              for (final activity in day.activities) ...[
                CheckInActivityCard(
                  activity: activity,
                  onTap: () {
                    if (activity.visited) return;
                    onMissedPlace(activity.id);
                  },
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
