import 'package:flutter/material.dart';
import '../../models/trip.dart';
import '../../theme/theme.dart';
import '../../widgets/activity_card.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/primary_button.dart';

class InitialItineraryScreen extends StatefulWidget {
  const InitialItineraryScreen({
    super.key,
    required this.itinerary,
    required this.onStartExploring,
    required this.onBack,
  });

  final Itinerary itinerary;
  final VoidCallback onStartExploring;
  final VoidCallback onBack;

  @override
  State<InitialItineraryScreen> createState() => _InitialItineraryScreenState();
}

class _InitialItineraryScreenState extends State<InitialItineraryScreen> {
  int _selectedDay = 1;

  @override
  Widget build(BuildContext context) {
    final day = widget.itinerary.days.firstWhere((d) => d.dayNumber == _selectedDay);
    return Scaffold(
      backgroundColor: AppColors.background,
      body: FigmaDeviceFrameWrapper(
        showHomeIndicator: false,
        child: Column(
          children: [
            Container(
              decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border))),
              padding: const EdgeInsets.fromLTRB(12, 12, 24, 12),
              child: Row(
                children: [
                  IconButton(onPressed: widget.onBack, icon: const Icon(Icons.chevron_left, size: 24)),
                  const SizedBox(width: 4),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('SeoulFit AI', style: AppTextStyles.headingSmall.copyWith(fontSize: 16)),
                      Text('Initial Itinerary', style: AppTextStyles.caption),
                    ],
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(color: const Color(0xFFEAEFE2), borderRadius: BorderRadius.circular(6)),
                    child: Text(
                      widget.itinerary.preferences.groupSize.toUpperCase(),
                      style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700),
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(20),
                child: SizedBox(
                  height: 128,
                  width: double.infinity,
                  child: Image.asset('assets/images/map-seoul.png', fit: BoxFit.cover),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: DayTabs(days: widget.itinerary.days, selectedDay: _selectedDay, onSelect: (d) => setState(() => _selectedDay = d)),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  for (final activity in day.activities) ...[
                    ActivityCard(activity: activity),
                    const SizedBox(height: 12),
                  ],
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: PrimaryButton(label: 'Start Exploring', onPressed: widget.onStartExploring),
            ),
          ],
        ),
      ),
    );
  }
}
