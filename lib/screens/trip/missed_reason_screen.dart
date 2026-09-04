import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../models/trip.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/activity_card.dart';
import '../../widgets/primary_button.dart';

class MissedReasonScreen extends StatefulWidget {
  const MissedReasonScreen({
    super.key,
    required this.dayNumber,
    required this.activityId,
    required this.onConfirm,
    required this.onBack,
  });

  final int dayNumber;
  final String activityId;
  final VoidCallback onConfirm;
  final VoidCallback onBack;

  @override
  State<MissedReasonScreen> createState() => _MissedReasonScreenState();
}

class _MissedReasonScreenState extends State<MissedReasonScreen> {
  MissedReason _reason = MissedReason.notEnoughTime;

  static const _options = [
    (MissedReason.notEnoughTime, '⏰ Not enough time'),
    (MissedReason.tooTired, '🏃 Too tired'),
    (MissedReason.didntFeelLikeIt, "💭 Didn't feel like it"),
    (MissedReason.other, '✏️ Other'),
  ];

  @override
  Widget build(BuildContext context) {
    final trip = context.watch<TripProvider>();
    final day = trip.itinerary!.days.firstWhere((d) => d.dayNumber == widget.dayNumber);
    final activity = day.activities.firstWhere((a) => a.id == widget.activityId);

    return Column(
      children: [
        Container(
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border))),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          child: Row(
            children: [
              GestureDetector(onTap: widget.onBack, child: const Icon(Icons.chevron_left, size: 20)),
              Expanded(
                child: Text(
                  "Place You Couldn't Visit",
                  textAlign: TextAlign.center,
                  style: AppTextStyles.headingSmall.copyWith(fontSize: 20),
                ),
              ),
              const SizedBox(width: 20),
            ],
          ),
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${day.areaName.toUpperCase()} · DAY ${widget.dayNumber}',
                  style: AppTextStyles.bodyMedium.copyWith(color: AppColors.accent, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 4),
                Text("Let us know why you couldn't make it", style: AppTextStyles.headingMedium.copyWith(fontSize: 22)),
                const SizedBox(height: 16),
                Opacity(opacity: 0.65, child: ActivityCard(activity: activity)),
                const SizedBox(height: 16),
                for (final option in _options) ...[
                  _ReasonOption(
                    label: option.$2,
                    selected: _reason == option.$1,
                    onTap: () => setState(() => _reason = option.$1),
                  ),
                  const SizedBox(height: 10),
                ],
                const SizedBox(height: 8),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(color: AppColors.chipBackground, borderRadius: BorderRadius.circular(16)),
                  child: Row(
                    children: [
                      const Icon(Icons.auto_awesome, size: 16, color: AppColors.primary),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'This helps our AI adjust your upcoming recommendations',
                          style: AppTextStyles.bodySmall.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: PrimaryButton(
            label: 'Confirm',
            onPressed: () {
              trip.markMissed(widget.activityId, _reason);
              widget.onConfirm();
            },
          ),
        ),
      ],
    );
  }
}

class _ReasonOption extends StatelessWidget {
  const _ReasonOption({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        decoration: BoxDecoration(
          color: selected ? AppColors.chipBackground : Colors.white,
          border: Border.all(color: selected ? AppColors.primary : AppColors.border, width: selected ? 1.5 : 1),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              label,
              style: AppTextStyles.bodyLarge.copyWith(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: selected ? AppColors.primary : AppColors.textPrimary,
              ),
            ),
            Icon(
              selected ? Icons.radio_button_checked : Icons.radio_button_off,
              color: selected ? AppColors.primary : AppColors.border,
            ),
          ],
        ),
      ),
    );
  }
}
