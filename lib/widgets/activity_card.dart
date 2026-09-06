import 'package:flutter/material.dart';
import '../models/trip.dart';
import '../theme/theme.dart';
import 'category_tag.dart';
import 'poi_photo.dart';
import 'poi_summary.dart';

/// A read-only itinerary activity row (used on Initial Itinerary).
class ActivityCard extends StatelessWidget {
  const ActivityCard({super.key, required this.activity, this.onTap});

  final TripActivity activity;

  /// Opens the stop's detail sheet. Optional so the mock build, which has no
  /// backend to ask for arrival tips, can leave the card inert.
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final card = Container(
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
          PoiPhoto(
            name: activity.title,
            type: activity.poiType,
            size: 80,
            asset: activity.imageAsset,
          ),
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
                // The place's own description, fetched per card. The
                // planner's note stands in until it lands, so the line is
                // never blank and never a spinner.
                PoiSummary(
                  name: activity.title,
                  type: activity.poiType,
                  fallback: activity.description,
                ),
              ],
            ),
          ),
        ],
      ),
    );

    if (onTap == null) return card;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: card,
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
                PoiPhoto(
            name: activity.title,
            type: activity.poiType,
            size: 64,
            asset: activity.imageAsset,
          ),
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
  const CheckInActivityCard({
    super.key,
    required this.activity,
    required this.onToggleVisited,
    required this.onMissed,
  });

  final TripActivity activity;

  /// Stamps the stop, or un-stamps it. The whole card is the target.
  final VoidCallback onToggleVisited;

  /// Records why a stop went unvisited. Deliberately a separate, smaller
  /// control: tapping a stop means "I was here", and routing that to the
  /// missed-reason screen — as this card used to — left no way to check
  /// anything in at all.
  final VoidCallback onMissed;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onToggleVisited,
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
            PoiPhoto(
            name: activity.title,
            type: activity.poiType,
            size: 64,
            asset: activity.imageAsset,
          ),
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
                  if (!activity.visited)
                    GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTap: onMissed,
                      child: Padding(
                        padding: const EdgeInsets.only(top: 2, bottom: 2),
                        child: Text(
                          "Couldn't make it?",
                          style: AppTextStyles.caption.copyWith(
                            color: AppColors.textSecondary,
                            decoration: TextDecoration.underline,
                          ),
                        ),
                      ),
                    ),
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
