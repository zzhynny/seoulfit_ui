import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/activity_card.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/primary_button.dart';

class MakeTripYoursScreen extends StatefulWidget {
  const MakeTripYoursScreen({super.key, required this.onOptimize, required this.onBack});

  final VoidCallback onOptimize;
  final VoidCallback onBack;

  @override
  State<MakeTripYoursScreen> createState() => _MakeTripYoursScreenState();
}

class _MakeTripYoursScreenState extends State<MakeTripYoursScreen> {
  String? _expandedId;

  @override
  Widget build(BuildContext context) {
    final trip = context.watch<TripProvider>();
    final itinerary = trip.itinerary!;
    final day = itinerary.days.firstWhere((d) => d.dayNumber == trip.selectedDay);
    return Scaffold(
      backgroundColor: AppColors.background,
      body: FigmaDeviceFrameWrapper(
        showHomeIndicator: false,
        child: Column(
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
                    const SizedBox(height: 12),
                  ],
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: PrimaryButton(label: 'Optimize My Trip', onPressed: widget.onOptimize),
            ),
          ],
        ),
      ),
    );
  }
}
