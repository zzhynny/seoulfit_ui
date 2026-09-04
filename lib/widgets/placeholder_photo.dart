import 'package:flutter/material.dart';
import '../theme/theme.dart';

/// Renders real place/content photography when [asset] is provided (from
/// assets downloaded via Figma), and falls back to a stylized placeholder
/// block otherwise — for content that would come from a backend (e.g.
/// Google Places photos) once the data layer is swapped in.
class PlaceholderPhoto extends StatelessWidget {
  const PlaceholderPhoto({
    super.key,
    this.icon = Icons.image_outlined,
    this.borderRadius = 12,
    this.size,
    this.asset,
    this.fit = BoxFit.cover,
  });

  final IconData icon;
  final double borderRadius;
  final double? size;
  final String? asset;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    if (asset != null) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(borderRadius),
        child: Image.asset(
          asset!,
          width: size,
          height: size,
          fit: fit,
        ),
      );
    }
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: AppColors.chipBackground,
        borderRadius: BorderRadius.circular(borderRadius),
      ),
      alignment: Alignment.center,
      child: Icon(icon, color: AppColors.primary.withValues(alpha: 0.6), size: 28),
    );
  }
}
