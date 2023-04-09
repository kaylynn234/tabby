import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import GitHubIcon from '@mui/icons-material/GitHub';
import SettingsIcon from '@mui/icons-material/Settings';
import LogoutIcon from '@mui/icons-material/Logout';
import PersonIcon from '@mui/icons-material/Person';

import AppBar from '@mui/material/AppBar';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import PopupState, { bindMenu, bindTrigger } from 'material-ui-popup-state';
import Head from 'next/head';
import { useSession } from 'next-auth/react';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Divider from '@mui/material/Divider';
import ListItemIcon from '@mui/material/ListItemIcon';

export const metadata = {
  title: 'Tabby',
  description: 'A friendly Discord bot'
}

type LayoutProps = {
  children: React.ReactNode,
};

export default function Layout({ children }: LayoutProps) {
  let { status, data } = useSession();
  let accountMenu;

  if (status !== 'authenticated') {
    accountMenu = (
      <PopupState variant='popover'>
        {(popupState) => (
          <>
            <Button
              variant='contained'
              startIcon={<Avatar src={data?.user?.image || undefined} />}
              endIcon={popupState.isOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              disableElevation
              {...bindTrigger(popupState)}
            >
              {data?.user?.name || 'Account'}
            </Button>
            <Menu
              {...bindMenu(popupState)}
              anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
              transformOrigin={{ vertical: 'top', horizontal: 'center' }}
            >
              <MenuItem>
                <ListItemIcon>
                  <SettingsIcon fontSize='small' />
                </ListItemIcon>
                Dashboard
              </MenuItem>
              <Divider />
              <MenuItem>
                <ListItemIcon>
                  <LogoutIcon fontSize='small' color='error' />
                </ListItemIcon>
                Log out
              </MenuItem>
            </Menu>
          </>
        )}
      </PopupState>
    );
  } else {
    accountMenu = (
      <Paper>
        <Button variant='outlined' startIcon={<PersonIcon />}>
          Login with Discord
        </Button>
      </Paper>
    );
  }

  return (
    <>
      <AppBar position='sticky'>
        <Toolbar>
          <Container>
            <Stack direction='row' spacing={1} sx={{ alignItems: 'center' }}>
              <Avatar src='/tabby_icon_light.png' />
              <Typography variant='h5' sx={{ flexGrow: 1, display: 'block' }}>
                Tabby
              </Typography>
              <IconButton
                href='https://github.com/kaylynn234/tabby'
                target='_blank'
                rel='noopener noreferrer'
                size='small' 
              >
                <GitHubIcon sx={{ color: 'primary.contrastText' }} />
              </IconButton>
              {accountMenu}
            </Stack>
          </Container>
        </Toolbar>
      </AppBar>
      <main>
        {children}
      </main>
    </>
  )
}
