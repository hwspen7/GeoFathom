"""Portable PDF figures and a complete machine-readable research archive."""
import base64
import io
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from reportlab.graphics.shapes import Drawing, PolyLine, Line, String, Circle


def number(value):
    return 'undefined' if value is None else f'{value:.7g}' if isinstance(value,(float,int)) else str(value)


def response_figure(points, title, x_label):
    """Vector response plot retained as selectable PDF text and vector lines."""
    points = sorted(points)
    drawing = Drawing(450,170)
    xs, ys = zip(*points)
    xmin,xmax=min(xs),max(xs)
    ymin,ymax=min(ys),max(ys)
    def xy(x,y):
        return 55+365*(x-xmin)/(xmax-xmin or 1), 35+100*(y-ymin)/(ymax-ymin or 1)
    drawing.add(String(55,153,title[:85],fontSize=9))
    drawing.add(Line(55,35,420,35,strokeColor=colors.grey))
    drawing.add(Line(55,35,55,135,strokeColor=colors.grey))
    drawing.add(PolyLine([v for x,y in points for v in xy(x,y)],strokeColor=colors.black,strokeWidth=1))
    for x,y in points:
        px,py=xy(x,y)
        drawing.add(Circle(px,py,2,fillColor=colors.black))
    for x in [xmin,xmax]:
        drawing.add(String(xy(x,ymin)[0],21,number(x),fontSize=8))
    for y in [ymin,ymax]:
        drawing.add(String(1,xy(xmin,y)[1],number(y),fontSize=8))
    drawing.add(String(140,5,x_label,fontSize=8))
    return drawing


def make_report(result, cancel=None):
    from .cancellation import checkpoint
    styles = getSampleStyleSheet()
    stream = io.BytesIO()
    story=[]
    def paragraph(text, style='BodyText'):
        story.append(Paragraph(escape(str(text)).replace('\n','<br/>'), styles[style]))
        story.append(Spacer(1,5))
    def table(rows, widths=None):
        wrapped=[[Paragraph(escape(number(cell)),styles['BodyText']) for cell in row] for row in rows]
        item=Table(wrapped,colWidths=widths,repeatRows=1,hAlign='LEFT')
        item.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.25,colors.lightgrey),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story.append(item);story.append(Spacer(1,10))
    paragraph(result['title'],'Title')
    manifest=result['manifest'];source=manifest['source'];grid=manifest['grid']
    paragraph('GeoFathom research report | '+result['mode'],'Heading2')
    paragraph('Generated '+manifest['created_at'])
    paragraph('Study area and source','Heading2')
    table([['Field','Recorded value'],['Source',source['name']],['Image ID',source['id']],
        ['Source SHA-256',source['sha256']],['Provenance',source.get('provenance','Not recorded')],
        ['Acquired',source.get('acquired_at') or 'Not recorded'],
        ['Vertical datum',source.get('vertical_datum') or 'Not declared'],
        ['Projected grid',grid['crs']],['Window (rows, columns)',str(grid['shape'])],
        ['Affine transform',str(grid['transform'])],['Source valid cells',grid['valid_source_cells']]], [115,335])
    geometry=manifest['input']['base']['geometry']
    paragraph('Exact WGS84 study geometry is included in experiment.json. Geometry type: '+geometry['type']+'.')
    paragraph('Methods and parameters','Heading2')
    paragraph(manifest['method'])
    if result.get('comparison_warning'):paragraph(result['comparison_warning'])
    for run in result['runs']:
        checkpoint(cancel)
        paragraph(run['label'],'Heading3')
        # Display parameters used by this operation; the manifest retains the
        # entire validated request, including unrelated engine defaults.
        from .research import SCENARIO_PARAMETERS
        operation=run['input']['operation']
        relevant={'operation',*SCENARIO_PARAMETERS[operation]}
        if operation in {'volume','cutfill_map'}:
            relevant.update({'design_max_grade','elevation_sigma_m'})
        if operation in {'visibility','viewshed_multi'}:
            relevant.update({'point','observer_points','dsm_image_id'})
        if operation=='flow_accumulation':relevant.add('external_inflow_image_id')
        parameters={k:v for k,v in run['input'].items() if k in relevant and v is not None}
        paragraph('; '.join(f'{k}={v}' for k,v in parameters.items()))
        paragraph(run['warning'])
        if run.get('quality'):
            paragraph('Quality: '+str(run['quality']))
    paragraph('Results and figures','Heading2')
    for product in result['products']+result['differences']:
        checkpoint(cancel)
        raster=product['raster']
        content=[Paragraph(escape(product['name'])+' ('+escape(raster['unit'])+')',styles['Heading3'])]
        raw=io.BytesIO(base64.b64decode(raster['png'].split(',',1)[1]))
        pic=Image(raw)
        ratio=min(400/pic.imageWidth,210/pic.imageHeight)
        pic.drawWidth=pic.imageWidth*ratio;pic.drawHeight=pic.imageHeight*ratio
        content.append(pic)
        content.append(Paragraph('North-up map preview; WGS84 corners: '+escape(str(raster['corners'])),styles['BodyText']))
        content.append(Paragraph('Legend: '+escape('; '.join(f"{r['label']} [{r['color']}]" for r in raster['legend'])),styles['BodyText']))
        story.append(KeepTogether(content));story.append(Spacer(1,10))
        if product.get('statistics'):
            paragraph('Difference statistics: '+str(product['statistics']))
    # Split wide scenario tables into groups, keeping all scenarios and metrics.
    for start in range(0,len(result['runs']),3):
        group=result['runs'][start:start+3]
        table([['Metric',*[r['label'] for r in group]]]+[
            [row['metric'],*row['values'][start:start+3]] for row in result['metric_table']],
            [180]+[270/len(group)]*len(group))
    if result['sensitivity']:
        paragraph('One-at-a-time sensitivity','Heading2')
        paragraph('Response slopes are finite differences from the baseline: (response - baseline response) / (parameter - baseline parameter). A zero step has no derivative.')
        keys=set(result['sensitivity'][0]['metrics'])
        # Plot all changing metrics, not a hardcoded subset of the engine output.
        for key in sorted(keys):
            points=[(r['value'],r['metrics'][key]) for r in result['sensitivity'] if key in r['metrics']]
            if len(points)>1 and max(y for _,y in points)!=min(y for _,y in points):
                story.append(response_figure(points,key,result['sensitivity'][0]['parameter']))
    if result['uncertainty']:
        uncertainty=result['uncertainty']
        paragraph('Uncertainty model and coverage intervals','Heading2')
        paragraph(uncertainty['warning'])
        paragraph('; '.join(f'{k}: {uncertainty[k]}' for k in ['model','sigma_m','seed','generator','samples','coverage','interval_type']))
        table([['Metric','Mean','Std','Low','High']]+[
            [k,v['mean'],v['std'],v['low'],v['high']] for k,v in uncertainty['metrics'].items()], [170,70,70,70,70])
        paragraph('Numerical stability (split-half endpoint difference)','Heading3')
        table([['Metric','Endpoint difference','Mean standard error']]+[
            [k,v['split_half_endpoint_difference'],v['mean_standard_error']] for k,v in uncertainty['metrics'].items()], [230,110,110])
    paragraph('Reproducibility and limitations','Heading2')
    paragraph('POST experiment.json to /terrain/research/analyze with the unchanged source available. '
        'The archive includes all output GeoTIFFs, preview images, metrics, uncertainty/sensitivity tables and manifest.json.')
    paragraph('Runtime: '+str(manifest['software']))
    for limitation in manifest['limitations']:paragraph(limitation)
    for reference in manifest['references']:paragraph(reference)
    def footer(canvas, doc):
        canvas.setFont('Helvetica',8)
        canvas.drawString(40,25,'GeoFathom | '+result['mode']+' | '+str(doc.page))
    checkpoint(cancel)
    SimpleDocTemplate(stream,pagesize=(530,750),rightMargin=40,leftMargin=40,
                      topMargin=36,bottomMargin=40).build(story,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()
