import 'package:flutter/material.dart';
import '../models/trip.dart';
import '../theme/theme.dart';

class CategoryColors {
  const CategoryColors(this.background, this.foreground);
  final Color background;
  final Color foreground;
}

CategoryColors categoryColorsFor(ActivityCategory category) {
  switch (category) {
    case ActivityCategory.culture:
    case ActivityCategory.teaHouse:
    case ActivityCategory.nature:
      return const CategoryColors(Color(0xFFEAEFEA), AppColors.primary);
    case ActivityCategory.food:
      return const CategoryColors(Color(0xFFFDF0EE), AppColors.accent);
    case ActivityCategory.shopping:
      return const CategoryColors(Color(0xFFFFF9E6), Color(0xFF73591A));
    case ActivityCategory.crafts:
      return const CategoryColors(AppColors.border, AppColors.textSecondary);
  }
}

class CategoryTag extends StatelessWidget {
  const CategoryTag({super.key, required this.category});

  final ActivityCategory category;

  @override
  Widget build(BuildContext context) {
    final colors = categoryColorsFor(category);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: colors.background,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        category.label.toUpperCase(),
        style: AppTextStyles.caption.copyWith(
          color: colors.foreground,
          fontWeight: FontWeight.w700,
          fontSize: 10,
        ),
      ),
    );
  }
}
