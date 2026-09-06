import 'package:flutter/material.dart';
import '../theme/theme.dart';

/// Renders real place/content photography, falling back to a stylized
/// placeholder block.
///
/// [asset] is bundled artwork (the Figma downloads the mock data points at);
/// [url] is a remote photo resolved from the backend's `/poi-image`. The
/// asset wins when both are set, and a URL that fails to load degrades to
/// the placeholder rather than a broken-image box.
class PlaceholderPhoto extends StatelessWidget {
  const PlaceholderPhoto({
    super.key,
    this.icon = Icons.image_outlined,
    this.borderRadius = 12,
    this.size,
    this.asset,
    this.url,
    this.fit = BoxFit.cover,
  });

  final IconData icon;
  final double borderRadius;
  final double? size;
  final String? asset;
  final String? url;
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
    if (url != null && url!.isNotEmpty) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(borderRadius),
        child: Image.network(
          url!,
          width: size,
          height: size,
          fit: fit,
          errorBuilder: (_, _, _) => _placeholder(),
          loadingBuilder: (context, child, progress) =>
              progress == null ? child : _placeholder(),
        ),
      );
    }
    return _placeholder();
  }

  Widget _placeholder() {
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
