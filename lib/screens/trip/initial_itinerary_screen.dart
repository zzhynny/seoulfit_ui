import 'package:flutter/material.dart';
import '../../models/trip.dart';
import '../../theme/theme.dart';
import '../../widgets/activity_card.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/itinerary_detail.dart';
import '../../widgets/route_map.dart';
import '../../widgets/primary_button.dart';
import 'place_detail_sheet.dart';

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
    return Column(
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
              PlanScoreChip(
                feasibility: widget.itinerary.feasibilityScore,
                overall: widget.itinerary.overallScore,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          // Was Image.asset('map-seoul.png') — a Figma illustration of a map,
          // not the trip. Same real map as Final Route, following the day
          // tabs below it.
          child: RouteMap(
            itinerary: widget.itinerary,
            height: 128,
            onlyDay: _selectedDay,
          ),
        ),
        if (widget.itinerary.summary.trim().isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: TripSummaryText(summary: widget.itinerary.summary),
          ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: DayTabs(days: widget.itinerary.days, selectedDay: _selectedDay, onSelect: (d) => setState(() => _selectedDay = d)),
        ),
        if (day.estimatedCost.trim().isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: DayCostChip(estimatedCost: day.estimatedCost),
          ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              for (final activity in day.activities) ...[
                ActivityCard(
                  activity: activity,
                  onTap: () => showPlaceDetailSheet(context, activity),
                ),
                const SizedBox(height: 12),
              ],
              if (widget.itinerary.sources.isNotEmpty) ...[
                const SizedBox(height: 4),
                SourcesCard(sources: widget.itinerary.sources),
                const SizedBox(height: 12),
              ],
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: PrimaryButton(label: 'Start Exploring', onPressed: widget.onStartExploring),
        ),
      ],
    );
  }
}
