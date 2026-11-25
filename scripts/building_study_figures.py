"""Render recorded building study results through the existing scientific studio."""
import argparse
import csv
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def csv_text(headers, rows):
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue()


def render_study(comparison, training, output):
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = json.loads(Path(comparison).read_text())
    scored = report['test'] if report['test_evaluated'] else {k: v['selected'] for k, v in report['validation'].items()}
    names = {'hotosm-dinov3s-buildings': 'HOT DINOv3', 'whu-unetplusplus-efficientnet-b4': 'WHU UNet++',
             'city-adapted-unetplusplus': 'WHU head adaptation', 'city-decoder-unetplusplus': 'WHU decoder adaptation'}
    rows = []
    for identifier, value in scored.items():
        metrics = value['aggregate']
        rows.append([names.get(identifier, identifier), metrics['classes'][1]['f1'], metrics['objects_50']['f1']])
    comparison_csv = csv_text(['model', 'Pixel F1', 'Object F1 at IoU 0.5'], rows)
    requests = [('building-city-comparison', dict(recipe='grouped_bar', csv=comparison_csv, x='model',
        columns=['Pixel F1', 'Object F1 at IoU 0.5'], title='City-disjoint building study: 16 test chips', y_label='F1 score'))]
    for index, file in enumerate(training):
        fit = json.loads(Path(file).read_text())
        history = [row for row in fit['history'] if row['training_loss'] is not None]
        text = csv_text(['epoch', 'Training loss', 'Validation loss'],
                        [[r['epoch'], r['training_loss'], r['validation_loss']] for r in history])
        requests.append(('building-city-learning-'+fit['parameters']['mode'], dict(recipe='multi_line', csv=text,
            x='epoch', columns=['Training loss', 'Validation loss'], title='Building '+fit['parameters']['mode']+' adaptation',
            x_label='Epoch', y_label='Composite segmentation loss')))
    for stem, arguments in requests:
        (output/(stem+'.csv')).write_text(arguments['csv'], encoding='utf-8')
        for extension in ('png', 'svg'):
            request = StudioInput(**arguments, width_mm=180, height_mm=115, dpi=300, format=extension)
            data, metadata, table = render(request)
            if extension == 'svg':
                data = ('\n'.join(line.rstrip() for line in data.decode().splitlines())+'\n').encode()
            (output/(stem+'.'+extension)).write_bytes(data)
            if extension == 'png':
                receipt = {'input': request.model_dump(), 'render': metadata,
                           'dataset_fingerprint': report['dataset_fingerprint'],
                           'selection_sha256': report['selection']['sha256']}
                (output/(stem+'.figure.json')).write_text(json.dumps(receipt, indent=2, allow_nan=False)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--training', type=Path, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render_study(args.comparison, args.training, args.output)


if __name__ == '__main__':
    main()
