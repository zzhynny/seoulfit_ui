import 'package:flutter/material.dart';
import '../models/trip.dart';
import '../theme/theme.dart';
import 'category_tag.dart';
import 'placeholder_photo.dart';

/// A read-only itinerary activity row (used on Initial Itinerary).
class ActivityCard extends StatelessWidget {
  const ActivityCard({super.key, required this.activity});

  final TripActivity activity;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(AppRadii.lg),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          PlaceholderPhoto(size: 80, borderRadius: 12, asset: activity.imageAsset),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      activity.time,
                      style: AppTextStyles.caption.copyWith(
                        color: AppColors.primary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    CategoryTag(category: activity.category),
                  ],
                ),
                const SizedBox(height: 4),
                Text(activity.title, style: AppTextStyles.headingSmall.copyWith(fontSize: 16)),
                const SizedBox(height: 4),
                Text(
                  activity.description,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTextStyles.bodySmall,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// A togglable version used on "Make This Trip Yours", with an optional
/// expanded AI-insight panel.
class ToggleActivityCard extends StatelessWidget {
  const ToggleActivityCard({
    super.key,
    required this.activity,
    required this.onToggle,
    this.expanded = false,
  });

  final TripActivity activity;
  final ValueChanged<bool> onToggle;
  final bool expanded;

  @override
  Widget build(BuildContext context) {
    return AnimatedOpacity(
      duration: const Duration(milliseconds: 200),
      opacity: activity.included ? 1 : 0.4,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surface,
          border: Border.all(
            color: expanded ? AppColors.primary : AppColors.border,
            width: expanded ? 1.5 : 1,
          ),
          borderRadius: BorderRadius.circular(AppRadii.lg),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                PlaceholderPhoto(size: 64, borderRadius: 12, asset: activity.imageAsset),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            activity.time,
                            style: AppTextStyles.caption.copyWith(
                              color: AppColors.primary,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          CategoryTag(category: activity.category),
                        ],
                      ),
                      const SizedBox(height: 2),
                      Text(activity.title, style: AppTextStyles.headingSmall.copyWith(fontSize: 15)),
                    ],
                  ),
                ),
                Switch(
                  value: activity.included,
                  onChanged: onToggle,
                  activeThumbColor: Colors.white,
                  activeTrackColor: AppColors.primary,
                ),
              ],
            ),
            if (expanded && activity.aiInsight != null) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.chipBackground,
                  borderRadius: BorderRadius.circular(AppRadii.md),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.auto_awesome, size: 14, color: AppColors.primary),
                        const SizedBox(width: 6),
                        Text(
                          'SeoulFit AI Insight',
                          style: AppTextStyles.caption.copyWith(
                            color: AppColors.primary,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(activity.aiInsight!, style: AppTextStyles.bodySmall),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// A tappable check-in version used on Day Check-in.
class CheckInActivityCard extends StatelessWidget {
  const CheckInActivityCard({super.key, required this.activity, required this.onTap});

  final TripActivity activity;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surface,
          border: Border.all(
            color: activity.visited ? AppColors.primary : AppColors.border,
            width: activity.visited ? 1.5 : 1,
          ),
          borderRadius: BorderRadius.circular(AppRadii.lg),
        ),
        child: Row(
          children: [
            PlaceholderPhoto(size: 64, borderRadius: 12, asset: activity.imageAsset),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        activity.time,
                        style: AppTextStyles.caption.copyWith(
                          color: activity.visited ? AppColors.primary : const Color(0xFF8A8A93),
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      CategoryTag(category: activity.category),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(activity.title, style: AppTextStyles.headingSmall.copyWith(fontSize: 15)),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: activity.visited ? AppColors.chipBackground : Colors.transparent,
                shape: BoxShape.circle,
                border: Border.all(
                  color: activity.visited ? AppColors.primary : AppColors.border,
                  width: activity.visited ? 1.5 : 1.5,
                  style: activity.visited ? BorderStyle.solid : BorderStyle.solid,
                ),
              ),
              child: activity.visited
                  ? const Icon(Icons.check_circle, color: AppColors.primary, size: 18)
                  : null,
            ),
          ],
        ),
      ),
    );
  }
}
