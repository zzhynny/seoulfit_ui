import 'package:flutter/material.dart';
import '../../theme/theme.dart';

enum LensPhotoSource { camera, gallery }

class LensScanScreen extends StatelessWidget {
  const LensScanScreen({super.key, required this.onScan});

  final ValueChanged<LensPhotoSource> onScan;

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        Image.asset('assets/images/lens-scan-bg.png', fit: BoxFit.cover),
        Container(color: Colors.black.withValues(alpha: 0.35)),
        Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 8, 24, 0),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(30)),
                    child: Text('📷 Seoul Lens', style: AppTextStyles.caption.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.1),
                      border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                      borderRadius: BorderRadius.circular(30),
                    ),
                    child: Text('Seoul Open Data', style: AppTextStyles.caption.copyWith(color: Colors.white.withValues(alpha: 0.9), fontWeight: FontWeight.w600)),
                  ),
                ],
              ),
            ),
            const Spacer(),
            SizedBox(
              width: 220,
              height: 220,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  for (final alignment in [Alignment.topLeft, Alignment.topRight, Alignment.bottomLeft, Alignment.bottomRight])
                    Align(alignment: alignment, child: _cornerBracket(alignment)),
                  GestureDetector(
                    onTap: () => _showSourcePicker(context),
                    child: Container(
                      width: 64,
                      height: 64,
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.15),
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.white.withValues(alpha: 0.8)),
                      ),
                      child: const Icon(Icons.camera, color: Colors.white, size: 28),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Column(
                children: [
                  Text('Point at a Seoul landmark', style: AppTextStyles.headingSmall.copyWith(fontSize: 22, color: Colors.white)),
                  const SizedBox(height: 8),
                  Text(
                    'Take a photo or pick one from your gallery, and Seoul Lens will identify it with opening hours and more.',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodySmall.copyWith(color: Colors.white.withValues(alpha: 0.8)),
                  ),
                ],
              ),
            ),
            const Spacer(),
          ],
        ),
      ],
    );
  }

  Widget _cornerBracket(Alignment alignment) {
    return SizedBox(
      width: 24,
      height: 24,
      child: CustomPaint(painter: _BracketPainter(alignment: alignment)),
    );
  }

  void _showSourcePicker(BuildContext context) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (context) => Container(
        padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
        decoration: const BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.only(topLeft: Radius.circular(24), topRight: Radius.circular(24)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 36,
                height: 4,
                margin: const EdgeInsets.only(bottom: 20),
                decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)),
              ),
            ),
            Text('Seoul Lens', style: AppTextStyles.headingSmall.copyWith(fontSize: 24)),
            const SizedBox(height: 4),
            Text('Choose a photo source', style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary)),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: _sourceButton(context, '📷 Camera', LensPhotoSource.camera),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _sourceButton(context, '🖼️ Gallery', LensPhotoSource.gallery),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _sourceButton(BuildContext context, String label, LensPhotoSource source) {
    return SizedBox(
      height: 48,
      child: ElevatedButton(
        onPressed: () {
          Navigator.of(context).pop();
          onScan(source);
        },
        style: ElevatedButton.styleFrom(
          backgroundColor: const Color(0xFFE8EFEB),
          elevation: 0,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
        child: Text(label, style: AppTextStyles.bodyMedium.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700)),
      ),
    );
  }
}

class _BracketPainter extends CustomPainter {
  _BracketPainter({required this.alignment});
  final Alignment alignment;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;
    final path = Path();
    if (alignment == Alignment.topLeft) {
      path.moveTo(0, size.height);
      path.lineTo(0, 0);
      path.lineTo(size.width, 0);
    } else if (alignment == Alignment.topRight) {
      path.moveTo(0, 0);
      path.lineTo(size.width, 0);
      path.lineTo(size.width, size.height);
    } else if (alignment == Alignment.bottomLeft) {
      path.moveTo(0, 0);
      path.lineTo(0, size.height);
      path.lineTo(size.width, size.height);
    } else {
      path.moveTo(size.width, 0);
      path.lineTo(size.width, size.height);
      path.lineTo(0, size.height);
    }
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
