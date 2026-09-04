import 'package:flutter/material.dart';
import '../models/trip.dart';
import '../theme/theme.dart';

class DayTabs extends StatelessWidget {
  const DayTabs({
    super.key,
    required this.days,
    required this.selectedDay,
    required this.onSelect,
  });

  final List<TripDay> days;
  final int selectedDay;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (final day in days)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: _DayTab(
                day: day,
                selected: day.dayNumber == selectedDay,
                onTap: () => onSelect(day.dayNumber),
              ),
            ),
        ],
      ),
    );
  }
}

class _DayTab extends StatelessWidget {
  const _DayTab({required this.day, required this.selected, required this.onTap});

  final TripDay day;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? AppColors.primary : AppColors.surface,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(AppRadii.md),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'Day ${day.dayNumber}',
              style: AppTextStyles.bodySmall.copyWith(
                fontWeight: FontWeight.w700,
                color: selected ? Colors.white : AppColors.textPrimary,
              ),
            ),
            Text(
              day.date,
              style: AppTextStyles.caption.copyWith(
                color: selected ? Colors.white.withValues(alpha: 0.9) : AppColors.textSecondary,
                fontWeight: FontWeight.w400,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
