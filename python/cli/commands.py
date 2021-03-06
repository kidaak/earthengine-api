#!/usr/bin/env python
"""Commands supported by the Earth Engine command line interface.

Each command is implemented by extending the Command class. Each class
defines the supported positional and optional arguments, as well as
the actions to be taken when the command is executed.
"""

import json
import os
import sys
import urlparse

import ee
import utils

ASSET_TYPE_FOLDER = 'Folder'
ASSET_TYPE_IMAGE_COLL = 'ImageCollection'


def _add_wait_arg(parser):
  parser.add_argument(
      '--wait', '-w', nargs='?', default=-1, type=int, const=sys.maxint,
      help=('Wait for the task to finish,'
            ' or timeout after the specified number of seconds.'
            ' Without this flag, the command just starts an export'
            ' task in the background, and returns immediately.'))


class AssetCommand(object):
  """Prints the metadata related to the asset with the specified asset_id."""

  name = 'asset'

  def __init__(self, parser):
    parser.add_argument('asset_id', help='ID of the asset to be loaded.')

  def run(self, args, config):
    config.ee_init()
    info = ee.data.getInfo(args.asset_id)
    if info:
      print info
    else:
      print 'No asset available with ID: %s' % args.asset_id


class ConfigCommand(object):
  """Prints or updates the configuration parameters used by the CLI tool."""

  name = 'config'

  def __init__(self, parser):
    subparsers = parser.add_subparsers(
        dest='sub_cmd', help='Supported config options')
    get_desc = 'Prints the configuration parameters.'
    get_parser = subparsers.add_parser(
        'get', description=get_desc, help=get_desc)
    get_parser.add_argument(
        'param', nargs='?', default=None,
        help='Parameter name (Optional).')
    set_desc = 'Updates the configuration parameters.'
    set_parser = subparsers.add_parser(
        'set', description=set_desc, help=set_desc)
    set_parser.add_argument('param', help='Parameter name.')
    set_parser.add_argument('value', help='New parameter value.')

  def get_config(self, args, config):
    if args.param:
      if utils.CONFIG_PARAMS.has_key(args.param):
        print '%s = %s' % (args.param, getattr(config, args.param))
      else:
        print 'Unknown configuration parameter: %s' % args.param
    else:
      for key in sorted(utils.CONFIG_PARAMS.keys()):
        print '%s = %s' % (key, getattr(config, key))

  def set_config(self, args, config):
    if args.param in utils.CONFIG_PARAMS:
      if args.param == 'refresh_token':
        confirm = utils.query_yes_no(
            'Are you sure you want to update the refresh token?')
        if not confirm:
          return
      setattr(config, args.param, args.value)
      print '%s = %s' % (args.param, getattr(config, args.param))
      config.save()
      print 'Configuration updated.'
    else:
      print 'Unknown configuration parameter: %s' % args.param

  def run(self, args, config):
    if args.sub_cmd == 'get':
      self.get_config(args, config)
    else:
      self.set_config(args, config)


class ExportCommand(object):
  """Exports an asset to Google Drive or Cloud Storage."""

  name = 'export'

  FEAT_FILE_FORMATS = ('CSV', 'GeoJSON', 'KML', 'KMZ')

  def __init__(self, parser):
    subparsers = parser.add_subparsers(
        dest='sub_cmd', help='Supported export options')

    export_img_desc = ('Exports an image asset to Drive or Cloud Storage.')
    export_img_parser = subparsers.add_parser(
        'image', description=export_img_desc, help=export_img_desc)
    self.setup_common_args(export_img_parser)
    self.setup_visualization_args(export_img_parser)
    export_img_parser.add_argument(
        '--max-pixels', type=int,
        help=('The maximum allowed number of pixels in the exported'
              ' image. The task will fail if the exported region covers more'
              ' pixels in the specified projection. Defaults to 100,000,000.'))
    export_img_parser.add_argument(
        '--bands', nargs='+',
        help=('Names of one or more bands that should be included in the'
              ' exported image. If unspecified, attempts to export all bands.'))

    export_vid_desc = 'Exports a video asset to Drive or Cloud Storage.'
    export_vid_parser = subparsers.add_parser(
        'video', description=export_vid_desc, help=export_vid_desc)
    self.setup_common_args(export_vid_parser)
    self.setup_visualization_args(export_vid_parser)
    export_vid_parser.add_argument(
        '--frame-rate', type=float,
        help=('A number between 0.1 and 100 describing the frame rate of'
              ' the exported video.'))

    export_table_desc = 'Exports a table to Drive or Cloud Storage.'
    export_table_parser = subparsers.add_parser(
        'table', description=export_table_desc, help=export_table_desc)
    self.setup_common_args(export_table_parser)
    export_table_parser.add_argument(
        '--file-format', help=('Output file format. Must be one of '
                               'CSV (default), GeoJSON, KML or KMZ.'))

  def setup_common_args(self, parser):
    """Sets up the parser with the arguments common for all exports."""
    _add_wait_arg(parser)
    parser.add_argument(
        '--config-json', '-cj',
        help='Path to a JSON file with export configuration parameters.')
    parser.add_argument(
        '--drive-folder', '-df',
        help=('Name of the Google Drive folder to export into. '
              'If not specified, the asset will be exported to the root.'))
    parser.add_argument(
        '--file-prefix', '-fp',
        help='A file name prefix to be added to all exported files.')
    parser.add_argument(
        '--gs-url', '-gu',
        help=('A URL that points to an export destination in Google Cloud'
              ' Storage. Must have the prefix \'gs://\'. The URL may'
              ' reference a bucket or a directory within one.'))
    parser.add_argument(
        '--desc', '-d', default='exportAssetExample',
        help='Description for the export task.')
    parser.add_argument(
        '--asset-id', '-ai',
        help='ID of the asset that needs to be exported.')
    parser.add_argument(
        '--json-file', '-jf',
        help='Path to a JSON file that describes the asset to be exported.')

  def setup_visualization_args(self, parser):
    """Set up the command to accept common visualization-related parameters."""
    parser.add_argument(
        '--region',
        help=('The lon,lat coordinates for a LinearRing or Polygon'
              ' specifying the region to export. Can be specified as a nested'
              ' list of numbers or a serialized string. Defaults to the'
              ' asset\'s region.'))
    parser.add_argument(
        '--scale', type=int,
        help=('The resolution in meters per pixel. Defaults to the native'
              ' resolution of the asset unless a crs_transform is specified.'))
    parser.add_argument(
        '--crs',
        help=('The coordinate reference system of the exported asset\'s'
              ' projection. Defaults to the asset\'s default projection.'))
    parser.add_argument(
        '--crs-transform',
        help=('A comma-separated string of 6 numbers describing'
              ' the affine transform of the coordinate reference system of the'
              ' exported asset\'s projection, in the order: xScale, yShearing,'
              ' xShearing, yScale, xTranslation and yTranslation. Defaults to'
              ' the asset\'s native CRS transform.'))
    parser.add_argument(
        '--dimensions',
        help=('The dimensions of the exported asset. Takes either a single'
              ' positive integer as the maximum dimension or "WIDTHxHEIGHT"'
              ' where WIDTH and HEIGHT are each positive integers.'))

  def run(self, args, config):
    """Starts an export task from the provided arguments."""
    if args.asset_id and args.json_file:
      print 'Specify asset ID or asset JSON, but not both'
      return
    elif not args.asset_id and not args.json_file:
      print 'One of asset ID or asset JSON file should be specified'
      return

    export_config = self.get_export_params(args)
    if export_config:
      print 'Initializing the export task with parameters:'
      for k, v in export_config.items():
        print '  %s: %s' % (k, v)
      print

    if args.file_prefix and '/' in args.file_prefix:
      raise Exception('File prefix must not contain \'/\' characters')
    if args.gs_url and args.drive_folder:
      raise Exception('Must not specify both Cloud Storage URL '
                      'and Drive folder.')

    if args.gs_url:
      parse_result = urlparse.urlparse(args.gs_url)
      if parse_result.scheme != 'gs':
        raise Exception('Invalid URL without the required prefix gs://')
      if not parse_result.netloc:
        raise Exception('Bucket name not specified in URL')
      export_config['outputBucket'] = parse_result.netloc
      prefix = parse_result.path.strip('/')
      if prefix:
        prefix += '/'
      if args.file_prefix:
        prefix += args.file_prefix
      if prefix:
        export_config['outputPrefix'] = prefix
      print 'Exporting to Google Cloud Storage...'
    else:
      if args.drive_folder:
        export_config['driveFolder'] = args.drive_folder
      if args.file_prefix:
        export_config['driveFileNamePrefix'] = args.file_prefix
      print 'Exporting to Google Drive...'

    config.ee_init()
    if args.sub_cmd == 'image':
      task_id = self.export_image(args, export_config)
    elif args.sub_cmd == 'video':
      task_id = self.export_video(args, export_config)
    elif args.sub_cmd == 'table':
      task_id = self.export_table(args, export_config)
    else:
      raise Exception('Unsupported export option: %s' % args.sub_cmd)

    if task_id is None:
      return
    print 'Started export task with ID: %s' % task_id
    if args.wait >= 0:
      print 'Waiting for the export task to complete...'
      utils.wait_for_task(task_id, args.wait)

  def get_export_params(self, args):
    export_config = {}
    if args.config_json:
      with open(os.path.expanduser(args.config_json)) as config_json:
        export_config = json.load(config_json)
    return export_config

  def get_visualization_params(self, args, export_config):
    if args.region:
      export_config['region'] = args.region
    if args.scale:
      export_config['scale'] = args.scale
    if args.crs:
      export_config['crs'] = args.crs
    if args.crs_transform:
      export_config['crs_transform'] = args.crs_transform
    if args.dimensions:
      if args.dimensions.isdigit():
        export_config['dimensions'] = int(args.dimensions)
      else:
        export_config['dimensions'] = args.dimensions

  def get_asset_to_export(self, args, asset_type):
    """Create an asset instance for export using the provided arguments."""
    if args.json_file:
      asset_path = os.path.expanduser(args.json_file)
      with open(asset_path) as json_file:
        asset_json = json_file.read()
        asset = ee.deserializer.fromJSON(asset_json)
        print 'Loaded asset from JSON file: %s' % asset_path
        return asset
    else:
      return asset_type(args.asset_id)

  def export_image(self, args, export_config):
    """Initiates an image export task."""
    self.get_visualization_params(args, export_config)
    if args.max_pixels:
      export_config['maxPixels'] = args.max_pixels
    image = self.get_asset_to_export(args, ee.Image)
    if args.bands:
      print 'Exporting image bands: %s' % args.bands
      image = image.select(args.bands)
    task = ee.batch.Export.image(image, args.desc, export_config)
    task.start()
    return task.id

  def export_video(self, args, export_config):
    """Initiates a video export task."""
    self.get_visualization_params(args, export_config)
    if args.frame_rate:
      if args.frame_rate < 0.1 or args.frame_rate > 100:
        print 'Frame rate must be in the interval [0.1,100].'
        return None
      else:
        export_config['framesPerSecond'] = args.frame_rate
    video = self.get_asset_to_export(args, ee.ImageCollection)
    task = ee.batch.Export.video(video, args.desc, export_config)
    task.start()
    return task.id

  def export_table(self, args, export_config):
    if args.file_format:
      if args.file_format not in ExportCommand.FEAT_FILE_FORMATS:
        print 'Unsupported output format: %s' % args.file_format
        return None
      export_config['fileFormat'] = args.file_format
    table = self.get_asset_to_export(args, ee.FeatureCollection)
    task = ee.batch.Export.table(table, args.desc, export_config)
    task.start()
    return task.id


class TasksCommand(object):
  """Lists or cancels the tasks submitted recently."""

  name = 'tasks'

  def __init__(self, parser):
    parser.add_argument(
        'task_id', nargs='*', help='Task ID list (Optional).')
    parser.add_argument(
        '--cancel', '-c', action='store_true',
        help=('Cancel the specified tasks. At least one task ID must be '
              'specified for cancellation.'))

  def cancel_tasks(self, tasks):
    for task in tasks:
      if task['state'] in utils.TASK_FINISHED_STATES:
        print 'Task %s already in state %s' % (task['id'], task['state'])
      else:
        print 'Cancelling task: %s' % task['id']
        task_obj = ee.batch.Task(task['id'], {
            'type': task['task_type'],
            'description': task['description'],
            'state': task['state']
        })
        task_obj.cancel()

  def list_tasks(self, tasks):
    descs = [utils.truncate(task['description'], 40) for task in tasks]
    desc_length = max(len(word) for word in descs)
    format_str = '{:25s} {:16s} {:%ds} {:10s} {:s}' % (desc_length + 1)
    for task in tasks:
      truncated_desc = utils.truncate(task['description'], 40)
      print format_str.format(
          task['id'], task['task_type'], truncated_desc,
          task['state'], task.get('error_message', '---'))

  def run(self, args, config):
    """Retrieves the task list with and filters it."""
    if args.cancel and not args.task_id:
      print 'One or more task IDs must be specified for cancelleation.'
      return
    config.ee_init()
    tasks = ee.data.getTaskList()
    filtered = [t for t in tasks if not args.task_id or t['id'] in args.task_id]
    processed = [t['id'] for t in filtered]
    if filtered:
      if args.cancel:
        self.cancel_tasks(filtered)
      else:
        self.list_tasks(filtered)
    not_found = set(args.task_id) - set(processed)
    if not_found:
      if processed:
        print
      print 'Failed to find tasks: %s' % ', '.join(not_found)


class AclCommand(object):
  """Prints or updates the access control list of the specified asset."""

  name = 'acl'

  def __init__(self, parser):
    parser.add_argument(
        'asset_id', help='ID of the asset whose ACL is to be inspected.')
    parser.add_argument(
        '--writers', '-w', nargs='*',
        help='Set the list of users with write permissions.')
    parser.add_argument(
        '--readers', '-r', nargs='*',
        help='Set the list of users with read permissions.')

  def run(self, args, config):
    config.ee_init()
    acl = ee.data.getAssetAcl(args.asset_id)
    if args.writers or args.readers:
      new_acl = acl.copy()
      if args.writers:
        new_acl['writers'] = args.writers
      read_public = args.readers and 'AllUsers' in args.readers
      new_acl['all_users_can_read'] = read_public
      if read_public and len(args.readers) > 1:
        print 'AllUsers are in readers list. Other readers will be ignored.'
      if not read_public and args.readers:
        new_acl['readers'] = args.readers
      print 'Updating ACL...'
      print 'Old: %s' % acl
      print 'New: %s' % new_acl
      del new_acl['owners']
      ee.data.setAssetAcl(args.asset_id, json.dumps(new_acl))
    else:
      print acl


class ListCommand(object):
  """Prints the contents of a folder or asset collection."""

  name = 'ls'

  def __init__(self, parser):
    parser.add_argument(
        'asset_id', nargs='*',
        help='A folder or image collection to be inspected.')
    parser.add_argument(
        '-l', action='store_true',
        help='Print output in long format.')
    parser.add_argument(
        '--max-items', '-m', default=-1, type=int,
        help='Maximum number of items to list for each collection.')

  def list_asset_content(self, asset, max_items, total_assets, long_format):
    try:
      list_req = {'id': asset}
      if max_items >= 0:
        list_req['num'] = max_items
      children = ee.data.getList(list_req)
      indent = ''
      if total_assets > 1:
        print '%s:' % asset
        indent = '  '
      if children:
        max_type_length = max([len(child['type']) for child in children])
        format_str = '%s{:%ds}{:s}' % (indent, max_type_length + 4)
        for child in children:
          if long_format:
            # Example output:
            # [Image]           user/test/my_img
            # [ImageCollection] user/test/my_coll
            print format_str.format('['+child['type']+']', child['id'])
          else:
            print child['id']
    except ee.EEException as e:
      print e

  def run(self, args, config):
    config.ee_init()
    if args.asset_id:
      assets = args.asset_id
    else:
      roots = ee.data.getAssetRoots()
      assets = [root['id'] for root in roots]
    count = 0
    for asset in assets:
      if count > 0:
        print
      self.list_asset_content(
          asset, args.max_items, len(assets), args.l)
      count += 1




class RmCommand(object):
  """Deletes the specified assets."""

  name = 'rm'

  def __init__(self, parser):
    parser.add_argument(
        'asset', nargs='+', help='Full path name of an asset to delete.')
    parser.add_argument(
        '--recursive', '-r', action='store_true',
        help='Recursively delete child assets.')
    parser.add_argument(
        '--dry-run', action='store_true',
        help=('Perform a dry run of the delete operation. Does not '
              'delete any assets.'))
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print the progress of the operation to the console.')

  def delete_asset(self, asset_id, recursive, verbose, dry_run):
    """Attempts to delete the specified asset or asset collection."""
    info = ee.data.getInfo(asset_id)
    if info is None:
      print 'No asset found by the ID: %s' % asset_id
      return
    if recursive:
      if info['type'] in (ASSET_TYPE_FOLDER, ASSET_TYPE_IMAGE_COLL):
        children = ee.data.getList({'id': asset_id})
        for child in children:
          self.delete_asset(child['id'], True, verbose, dry_run)
    if not dry_run:
      ee.data.deleteAsset(asset_id)
    if dry_run:
      print '[dry-run] Processing asset: %s' % asset_id
    elif verbose:
      print 'Deleted asset: %s' % asset_id

  def run(self, args, config):
    config.ee_init()
    for asset in args.asset:
      try:
        self.delete_asset(asset, args.recursive, args.verbose, args.dry_run)
      except ee.EEException as e:
        print 'Failed to delete %s. %s' % (asset, e)


